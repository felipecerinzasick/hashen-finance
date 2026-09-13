import base64
import hashlib
import os
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from .models import PortfolioSnapshot, StockQuoteHistory
from .views import stock_trailing_30d_performance

TEST_DASHBOARD_PASSWORD = 'test-dashboard-password'
TEST_DASHBOARD_PASSWORD_HASH = 'sha256$%s' % hashlib.sha256(TEST_DASHBOARD_PASSWORD.encode('utf-8')).hexdigest()


def auth_header(password=TEST_DASHBOARD_PASSWORD):
    credentials = base64.b64encode(('hashen:%s' % password).encode('utf-8')).decode('ascii')
    return {'HTTP_AUTHORIZATION': 'Basic %s' % credentials}


class DashboardAuthTests(TestCase):
    @patch.dict(os.environ, {'HASHEN_DASHBOARD_PASSWORD_HASH': TEST_DASHBOARD_PASSWORD_HASH})
    def test_dashboard_requires_basic_auth(self):
        response = self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 401)
        self.assertIn('Basic realm="Hashen private dashboard"', response['WWW-Authenticate'])

    @patch.dict(os.environ, {'HASHEN_DASHBOARD_PASSWORD_HASH': TEST_DASHBOARD_PASSWORD_HASH})
    def test_dashboard_rejects_old_default_password(self):
        response = self.client.get('/dashboard/', **auth_header('hashen123'))
        self.assertEqual(response.status_code, 401)

    @patch.dict(os.environ, {'HASHEN_DASHBOARD_PASSWORD_HASH': TEST_DASHBOARD_PASSWORD_HASH})
    def test_dashboard_accepts_configured_password_hash(self):
        response = self.client.get('/dashboard/', **auth_header())
        self.assertEqual(response.status_code, 200)


class PortfolioSnapshotLockTests(TestCase):
    @patch.dict(os.environ, {'HASHEN_DASHBOARD_PASSWORD_HASH': TEST_DASHBOARD_PASSWORD_HASH})
    @patch('blog.views.capture_report_share_price_history')
    @patch('blog.views.django_timezone.localdate')
    def test_month_end_lock_updates_current_mtd_snapshot(self, localdate, capture_prices):
        localdate.return_value = date(2026, 9, 1)
        capture_prices.return_value = {'saved': 0, 'failed': 0}

        response = self.client.post(
            '/api/portfolio-snapshot/',
            data={
                'action': 'lock_month_end',
                'snapshot_date': '2026-08-31',
                'cash_chf': '100.40',
                'stocks_chf': '200.50',
                'bitcoin_chf': '300.60',
                'bitcoin_amount': '0.42082719',
                'notes': 'Confirmed close.',
            },
            content_type='application/json',
            **auth_header()
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['snapshot']['date'], '2026-08-31')
        self.assertTrue(payload['snapshot']['locked'])
        self.assertEqual(payload['current']['date'], '2026-09-30')
        self.assertEqual(payload['current']['total_chf'], 602.0)

        august = PortfolioSnapshot.objects.get(snapshot_date=date(2026, 8, 31))
        september = PortfolioSnapshot.objects.get(snapshot_date=date(2026, 9, 30))
        self.assertTrue(august.locked)
        self.assertFalse(september.locked)
        self.assertEqual(september.cash_chf, august.cash_chf)
        self.assertEqual(september.stocks_chf, august.stocks_chf)
        self.assertEqual(september.bitcoin_chf, august.bitcoin_chf)

        snapshot_response = self.client.get('/api/portfolio-snapshot/', **auth_header())
        self.assertEqual(snapshot_response.status_code, 200)
        snapshot_payload = snapshot_response.json()
        self.assertFalse(snapshot_payload['pending_month_end'])

        progression_response = self.client.get('/api/wealth-progression/', **auth_header())
        self.assertEqual(progression_response.status_code, 200)
        progression_payload = progression_response.json()
        mtd_periods = [period for period in progression_payload['periods'] if period['is_current_mtd']]
        self.assertEqual(len(mtd_periods), 1)
        self.assertEqual(mtd_periods[0]['date'], '30.09.2026')
        self.assertEqual(mtd_periods[0]['total_chf'], 602.0)


class StockPerformanceTests(TestCase):
    @patch('blog.views.django_timezone.localdate')
    def test_trailing_30_day_performance_uses_saved_history(self, localdate):
        localdate.return_value = date(2026, 9, 12)
        StockQuoteHistory.objects.create(
            ticker='MSTR',
            symbol='MSTR',
            quote_date=date(2026, 8, 13),
            price='100.000000',
            currency='USD',
            source='Test',
        )

        performance = stock_trailing_30d_performance(
            {'ticker': 'MSTR', 'symbol': 'MSTR'},
            Decimal('125'),
            'USD',
        )

        self.assertIsNotNone(performance)
        self.assertEqual(performance['start_date'], date(2026, 8, 13))
        self.assertEqual(performance['pct'], Decimal('25.00'))
