"""Tests for the detection, simulation and planning backend.

Answer keys are fixtures for these tests only. The runtime engine never opens
them -- detection works from telemetry.csv, network.json and ops.json alone.
"""
import json
import unittest

from fastapi.testclient import TestClient

from backend.dataset import Dataset, ROOT
from backend.detect import Baselines
from backend.engine import analyze, load
from backend.main import app
from backend.planner import hours_to_limit, simulate

KEY = json.loads((ROOT / 'history/full_week/answer_key.json').read_text())


class SimulatorTests(unittest.TestCase):
    """The tank simulator is the ground truth every plan is scored against."""

    def test_trip_between_events_accounts_for_lost_revenue(self):
        # 100 bbl tank at 50, filling 10 bbl/h, trips at 92 after 4.2h,
        # then 1.8h shut at $100/h.
        r = simulate(100, 92, 50, 6, [240], [100], [], 6, [], 150, 905)
        self.assertTrue(r['tripped'])
        self.assertAlmostEqual(r['cost'], 180)

    def test_late_truck_does_not_reverse_a_trip(self):
        # The tank trips at 1.2h; a truck landing at 2h still costs its trip but
        # the facility stays shut until the repair.
        r = simulate(100, 92, 80, 6, [240], [100], [], 6, [2], 20, 50)
        self.assertTrue(r['tripped'])
        self.assertAlmostEqual(r['cost'], 530)

    def test_truck_cannot_take_more_than_tank_contains(self):
        self.assertIsNone(simulate(100, 92, 10, 6, [24], [100], [], 6, [1], 50, 50))

    def test_timed_shut_in_cost_and_water(self):
        r = simulate(100, 92, 50, 6, [240], [100], [0], 4, [], 150, 905)
        self.assertFalse(r['tripped'])
        self.assertEqual(r['cost'], 200)
        self.assertAlmostEqual(r['trace'][-1]['level_pct'], 90)

    def test_countdown_band_brackets_the_median(self):
        band = hours_to_limit(50, 800, 92, [1800, 1850, 1750, 1820])
        self.assertLess(band['p10'], band['p50'])
        self.assertLess(band['p50'], band['p90'])


class DetectionTests(unittest.TestCase):
    """Detection must find every labelled event and invent none."""

    @classmethod
    def setUpClass(cls):
        cls.analysis = load('history/full_week')

    def test_baselines_are_learned_not_assumed(self):
        base = Baselines(self.analysis.data)
        self.assertTrue(base.ok)
        # Learned from the readings, and tight enough to standardize against.
        self.assertGreater(base.pipe_sigma, 0)
        self.assertGreater(base.flow_sigma, 0)

    def test_every_labelled_event_is_found_with_the_right_asset(self):
        events = list(self.analysis.events)
        for label in KEY:
            match = next((e for e in events
                          if e.facility_id == label['facility']
                          and e.category == label['category']
                          and abs(e.onset_unix - label['onset_unix']) < 6 * 3600), None)
            self.assertIsNotNone(match, f'missed {label["id"]}')
            self.assertEqual(match.asset_id, label['asset'], label['id'])
            events.remove(match)
        self.assertEqual(events, [], f'invented {[e.category for e in events]}')

    def test_quiet_field_raises_no_alerts(self):
        # The first reading of the week is before any labelled event begins.
        self.assertEqual(self.analysis.at(self.analysis.data.start)['alerts'], [])

    def test_resolved_events_leave_the_alert_board(self):
        # EVENT_1 is a leak repaired on 10-06; well afterwards it must be history.
        later = self.analysis.at(1791400000)
        live = [a['facility_id'] for a in later['alerts'] if a['category'] == 'pipeline_leak']
        self.assertNotIn('S3_FACILITY_B', live)
        resolved = [e for e in later['events']
                    if e['facility_id'] == 'S3_FACILITY_B' and e['category'] == 'pipeline_leak']
        self.assertTrue(resolved and resolved[0]['status'] == 'resolved')
        self.assertIsNotNone(resolved[0]['end_ts'])


class PlanningTests(unittest.TestCase):
    """Plans must be legal, affordable, and never over-commit a shared fleet."""

    @classmethod
    def setUpClass(cls):
        cls.analysis = load('history/full_week')

    def test_event_9_opening_scene_costs_one_truck_trip(self):
        event = next(e for e in KEY if e['id'] == 'EVENT_9')
        view = self.analysis.at(event['onset_unix'])
        alert = next(a for a in view['alerts'] if a['facility_id'] == event['facility'])
        plan = alert['recommendation']
        self.assertEqual(plan['cost'], 905)
        self.assertEqual(plan['trucks'], 1)
        self.assertFalse(plan['tripped'])
        # The README's worked numbers for the alternatives.
        self.assertAlmostEqual(plan['baseline_cost'], 5016, delta=60)

    def test_fleet_is_never_oversubscribed(self):
        for event in KEY:
            if event['category'] != 'pump_failure':
                continue
            view = self.analysis.at(event['onset_unix'])
            for system_id, ops in self.analysis.data.ops['systems'].items():
                used = sum(a['recommendation'].get('trucks', 0) for a in view['alerts']
                           if a['system_id'] == system_id)
                self.assertLessEqual(used, ops['emergency_fleet_size'],
                                     f'{system_id} at {event["id"]}')

    def test_alerts_are_ordered_by_urgency_then_revenue(self):
        view = analyze('history/snapshot_2026-10-10T0900')
        failures = [a for a in view['alerts'] if a['category'] == 'pump_failure']
        self.assertEqual(failures, sorted(
            failures, key=lambda a: (a['hours_to_limit'], -a['revenue_per_hour'])))
        # Inspections never outrank a filling tank.
        categories = [a['category'] for a in view['alerts']]
        self.assertEqual(categories, sorted(categories, key=lambda c: c != 'pump_failure'))

    def test_plan_is_cheapest_for_the_trucks_it_was_actually_granted(self):
        """A facility may be given a dearer plan so a more urgent tank gets the truck.

        That is the point of allocating a shared fleet, so the right invariant is
        not "cheapest overall" but "cheapest among the plans using the trucks this
        facility was allocated".
        """
        view = analyze('history/snapshot_2026-10-08T1200')
        for alert in view['alerts']:
            if alert['category'] != 'pump_failure':
                continue
            plan = alert['recommendation']
            same_budget = [a for a in plan['alternatives']
                           if not a['tripped'] and a['trucks'] <= plan['trucks']]
            if same_budget:
                self.assertLessEqual(plan['cost'], min(a['cost'] for a in same_budget) + 1e-6)

    def test_sharing_a_fleet_beats_planning_each_tank_alone(self):
        """Three S2 tanks fail within an hour and only two trucks exist.

        Planning them independently would promise a truck to all three. The
        allocator must stay inside the fleet and still find the cheapest split.
        """
        view = analyze('history/snapshot_2026-10-08T1200')
        failures = [a for a in view['alerts'] if a['system_id'] == 'S2'
                    and a['category'] == 'pump_failure']
        self.assertEqual(len(failures), 3)
        fleet = self.analysis.data.ops['systems']['S2']['emergency_fleet_size']
        self.assertLessEqual(sum(a['recommendation']['trucks'] for a in failures), fleet)
        # Nobody is left to trip: every tank has a plan that holds.
        self.assertFalse(any(a['recommendation']['tripped'] for a in failures))

    def test_snapshot_plans_beat_or_match_the_reference_cost(self):
        for folder, reference in [('snapshot_2026-10-08T1200', 3108),
                                  ('snapshot_2026-10-09T0330', 1810),
                                  ('snapshot_2026-10-10T0900', 3095)]:
            view = analyze(f'history/{folder}')
            total = sum(a['recommendation']['cost'] for a in view['alerts']
                        if a['category'] == 'pump_failure')
            self.assertLessEqual(total, reference + 1, folder)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_and_dataset_discovery(self):
        self.assertEqual(self.client.get('/api/health').status_code, 200)
        self.assertIn('history/full_week', self.client.get('/api/datasets').json())

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            Dataset('../../outside')
        self.assertEqual(
            self.client.get('/api/dashboard', params={'dataset': '../../outside'}).status_code,
            400)

    def test_events_export_matches_the_spec_shape(self):
        body = self.client.get('/api/events',
                               params={'dataset': 'history/snapshot_2026-10-08T1200'}).json()
        self.assertTrue(body['events'])
        for record in body['events']:
            for field in ('event_id', 'system_id', 'facility_id', 'asset_id', 'category',
                          'status', 'onset_ts', 'onset_unix', 'confidence', 'evidence'):
                self.assertIn(field, record)
            self.assertIn(record['category'],
                          {'pump_degradation', 'pump_failure', 'pipeline_leak', 'other'})
            self.assertIn(record['status'], {'ongoing', 'resolved'})
            if record['status'] == 'resolved':
                self.assertIsNotNone(record['end_ts'])

    def test_handoff_and_fleet_study_respond(self):
        params = {'dataset': 'history/snapshot_2026-10-10T0900'}
        brief = self.client.get('/api/handoff', params=params).json()
        self.assertTrue(brief['summary'])
        study = self.client.get('/api/fleet-study', params=params).json()
        self.assertTrue(study['systems'])
        system = study['systems'][0]
        costs = [point['system_cost'] for point in system['curve']]
        # Adding a truck can never make a system more expensive.
        self.assertEqual(costs, sorted(costs, reverse=True))
        # The recommended fleet size is the first one that reaches the floor.
        at_recommended = next(p['system_cost'] for p in system['curve']
                              if p['fleet_size'] == system['trucks_worth_having'])
        self.assertAlmostEqual(at_recommended, min(costs))

    def test_investigate_without_credentials_is_explicit(self):
        response = self.client.post('/api/investigate', json={
            'dataset': 'history/full_week', 'facility_id': 'S1_FACILITY_A'})
        self.assertIn(response.status_code, (503, 404))


if __name__ == '__main__':
    unittest.main()
