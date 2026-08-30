import base64
import calendar
from datetime import datetime, timedelta, timezone
import json
import os
import ssl
from decimal import Decimal, InvalidOperation
from functools import wraps
from hmac import compare_digest
from urllib import parse, request as urlrequest
from urllib.error import URLError, HTTPError

from .models import Post, Comment, Resource, StockHolding, StockQuoteSnapshot, StockQuoteHistory, MemoNote, PortfolioSnapshot
from newsletter.models import Newsletter
from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404, HttpResponse, JsonResponse
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone as django_timezone
from django.utils.text import slugify
from django.views.decorators.csrf import ensure_csrf_cookie
from .forms import PostForm,ContactForm
from django.views.generic import (
    CreateView,
    ListView,
    DetailView,
    UpdateView,
    DeleteView
)

SATOSHIS_PER_BTC = 100000000
STOCK_QUOTE_STALE_AFTER = timedelta(hours=12)

MEMOS = [
    {
        'slug': 'mstr-short-horizon-june-2026',
        'title': 'MSTR Short-Horizon Bet',
        'subtitle': 'A deliberately shorter-time-horizon position memo after adding more exposure in late June.',
        'date': 'June 30, 2026',
        'asset': 'Strategy (MSTR)',
        'price_label': 'MSTR close on June 29, 2026',
        'price_value': '$92.68',
        'price_source': 'Yahoo Finance historical close',
        'source_url': 'https://finance.yahoo.com/quote/MSTR/history/',
        'position_note': 'Added roughly $900 more MSTR in the final days of June while already underwater.',
        'horizon': 'Late June to October 2026',
        'exit_note': 'It should be emotionally and tactically acceptable to sell in October if the trade works or the setup changes.',
        'thesis': [
            'The current price reflects a lot of fear and uncertainty.',
            'At this level, it is easy to imagine MSTR trading back in three-digit territory and potentially into higher three-digit numbers again.',
            'This is intentional: a shorter-time-horizon, high-beta bet rather than a permanent holding decision.',
            'If MSTR stays around these levels into the end of July, the plan is to continue buying more.',
            'The expectation for this specific trade is at least a double by October.',
        ],
        'guardrails': [
            'This memo is a record of intent, not a promise to hold regardless of new information.',
            'The October sell window is part of the plan, not a failure of conviction.',
            'Being underwater now is acknowledged up front so the decision can be judged against the thesis instead of the discomfort.',
        ],
        'tags': ['MSTR', 'short horizon', 'Bitcoin treasury', 'trade memo'],
    },
]

STOCK_HOLDINGS = [
    {'name': 'Argo Blockchain', 'ticker': '0XP', 'symbol': '0XP.DU', 'shares': Decimal('1100'), 'average_price': Decimal('0.232327273'), 'cost_currency': 'EUR', 'fallback_value': Decimal('13.20'), 'fallback_currency': 'EUR'},
    {'name': 'The Smarter Web Company', 'ticker': '3M8', 'symbol': '3M8.F', 'shares': Decimal('100'), 'average_price': Decimal('1.0760'), 'cost_currency': 'EUR', 'fallback_value': Decimal('28.10'), 'fallback_currency': 'EUR'},
    {'name': 'Metaplanet', 'ticker': 'DN3', 'symbol': 'DN3.F', 'shares': Decimal('2850'), 'average_price': Decimal('2.311705263'), 'cost_currency': 'EUR', 'fallback_value': Decimal('3021.00'), 'fallback_currency': 'EUR'},
    {'name': 'Shimano', 'ticker': 'SHM', 'symbol': 'SHM.F', 'shares': Decimal('5'), 'average_price': Decimal('176.3700'), 'cost_currency': 'EUR', 'fallback_value': Decimal('470.50'), 'fallback_currency': 'EUR'},
    {'name': 'Y6G0', 'ticker': 'Y6G0', 'symbol': 'Y6G0.F', 'shares': Decimal('160'), 'average_price': Decimal('18.8516125'), 'cost_currency': 'EUR', 'fallback_value': Decimal('1828.80'), 'fallback_currency': 'EUR'},
    {'name': 'Asset Entities', 'ticker': 'ASST', 'symbol': 'ASST', 'shares': Decimal('180'), 'average_price': Decimal('18.026504972'), 'cost_currency': 'USD', 'fallback_value': Decimal('1963.80'), 'fallback_currency': 'USD'},
    {'name': 'Canaan', 'ticker': 'CAN', 'symbol': 'CAN', 'shares': Decimal('231'), 'average_price': Decimal('2.601182684'), 'cost_currency': 'USD', 'fallback_value': Decimal('66.32'), 'fallback_currency': 'USD'},
    {'name': 'Cipher Mining', 'ticker': 'CIFR', 'symbol': 'CIFR', 'shares': Decimal('40'), 'average_price': Decimal('7.150048'), 'cost_currency': 'USD', 'fallback_value': Decimal('980.00'), 'fallback_currency': 'USD'},
    {'name': 'CleanSpark', 'ticker': 'CLSK', 'symbol': 'CLSK', 'shares': Decimal('96'), 'average_price': Decimal('15.303599667'), 'cost_currency': 'USD', 'fallback_value': Decimal('1396.80'), 'fallback_currency': 'USD'},
    {'name': 'Farfetch', 'ticker': 'FTCHQ', 'symbol': 'FTCHQ', 'shares': Decimal('290'), 'average_price': Decimal('1.465446552'), 'cost_currency': 'USD', 'fallback_value': Decimal('0.00'), 'fallback_currency': 'USD'},
    {'name': 'IREN', 'ticker': 'IREN', 'symbol': 'IREN', 'shares': Decimal('30'), 'average_price': Decimal('11.986714667'), 'cost_currency': 'USD', 'fallback_value': Decimal('1371.90'), 'fallback_currency': 'USD'},
    {'name': 'The Keel', 'ticker': 'KEEL', 'symbol': 'KEEL', 'shares': Decimal('710'), 'average_price': Decimal('2.388193352'), 'cost_currency': 'USD', 'fallback_value': Decimal('4075.40'), 'fallback_currency': 'USD'},
    {'name': 'MARA Holdings', 'ticker': 'MARA', 'symbol': 'MARA', 'shares': Decimal('164.0445'), 'average_price': Decimal('19.756089994'), 'cost_currency': 'USD', 'fallback_value': Decimal('2278.58'), 'fallback_currency': 'USD'},
    {'name': 'Strategy', 'ticker': 'MSTR', 'symbol': 'MSTR', 'shares': Decimal('42'), 'average_price': Decimal('166.790604452'), 'cost_currency': 'USD', 'fallback_value': Decimal('3651.06'), 'fallback_currency': 'USD'},
    {'name': 'PayPal', 'ticker': 'PYPL', 'symbol': 'PYPL', 'shares': Decimal('10'), 'average_price': Decimal('56.2350'), 'cost_currency': 'USD', 'fallback_value': Decimal('431.80'), 'fallback_currency': 'USD'},
    {'name': 'Riot Platforms', 'ticker': 'RIOT', 'symbol': 'RIOT', 'shares': Decimal('20'), 'average_price': Decimal('11.155072'), 'cost_currency': 'USD', 'fallback_value': Decimal('547.60'), 'fallback_currency': 'USD'},
    {'name': 'STRC', 'ticker': 'STRC', 'symbol': 'STRC', 'shares': Decimal('5.5'), 'average_price': Decimal('88.688002909'), 'cost_currency': 'USD', 'fallback_value': Decimal('466.73'), 'fallback_currency': 'USD'},
    {'name': 'Strategy Preferred STRD', 'ticker': 'STRD', 'symbol': 'STRD', 'shares': Decimal('5'), 'average_price': Decimal('61.640003'), 'cost_currency': 'USD', 'fallback_value': Decimal('281.40'), 'fallback_currency': 'USD'},
    {'name': 'TeraWulf', 'ticker': 'WULF', 'symbol': 'WULF', 'shares': Decimal('25'), 'average_price': Decimal('6.765072'), 'cost_currency': 'USD', 'fallback_value': Decimal('617.50'), 'fallback_currency': 'USD'},
]

STOCK_SNAPSHOT = {
    'label': 'IBKR snapshot · 01.07.2026 20:18 CET',
    'ibkr_nav_eur': Decimal('21804.00'),
    'table_value_eur': Decimal('21234.17'),
    'table_cost_eur': Decimal('28428.40'),
    'table_unrealized_eur': Decimal('-7194.23'),
    'usd_value': Decimal('18128.89'),
    'eur_value': Decimal('5361.60'),
    'usd_eur': Decimal('0.8755400909818527'),
    'eur_chf': Decimal('0.920490026473999'),
}

STOCK_SNAPSHOT_FX_TO_CHF = {
    'CHF': Decimal('1'),
    'EUR': STOCK_SNAPSHOT['eur_chf'],
    'USD': STOCK_SNAPSHOT['usd_eur'] * STOCK_SNAPSHOT['eur_chf'],
    'GBP': Decimal('1.07'),
}

STOCK_NOTES = {
    'ASST': {
        'category': 'Bitcoin-first asset-manager treasury bet',
        'why': 'Strive / Asset Entities is the Bitcoin-first asset-manager treasury bet. The uniqueness is Vivek/Strive\'s idea of using Bitcoin as the hurdle rate for capital allocation, not just holding BTC passively.',
    },
    'CFR': {
        'category': 'AI/HPC power conversion',
        'why': 'Hyperscale data-center developer born from Bitcoin mining. Cipher\'s value is increasingly about power sourcing, construction, and long-term HPC/data-center capacity rather than pure mining.',
    },
    'CIFR': {
        'category': 'AI/HPC power conversion',
        'why': 'Hyperscale data-center developer born from Bitcoin mining. Cipher\'s value is increasingly about power sourcing, construction, and long-term HPC/data-center capacity rather than pure mining.',
    },
    'CLSK': {
        'category': 'Bitcoin mining scale',
        'why': 'Energy-backed Bitcoin miner pivoting into large-scale AI compute infrastructure. CleanSpark\'s edge is execution at scale across energy, mining, and data-center campuses.',
    },
    'FTCHQ': {
        'category': 'Legacy distressed equity',
        'why': 'Residual distressed holding. Treat as a near-zero placeholder unless there is a separate recovery thesis.',
    },
    'DN3': {
        'category': 'Japan MSTR',
        'why': 'Japan\'s premier Bitcoin treasury company. Metaplanet is basically the Japanese MSTR play: BTC as reserve asset, BTC Yield as KPI, and capital markets used to grow Bitcoin per share.',
    },
    'IREN': {
        'category': 'AI/HPC power conversion',
        'why': 'Power-secured AI/HPC data-center platform with Bitcoin-mining roots. The uniqueness is huge renewable-powered infrastructure and the ability to convert mining sites into high-density compute.',
    },
    'KEEL': {
        'category': 'AI power infrastructure',
        'why': 'Former Bitfarms turned AI/HPC infrastructure play. The thesis is not just Bitcoin mining anymore; it is scarce power, grid interconnections, and data-center capacity for AI workloads.',
    },
    'MARA': {
        'category': 'Bitcoin mining scale',
        'why': 'One of the largest public Bitcoin miners and a major corporate BTC holder. MARA is a scale miner evolving into digital energy, compute, and infrastructure rather than just a hash-rate stock.',
    },
    'MSTR': {
        'category': 'Bitcoin treasury king',
        'why': 'The original and largest Bitcoin treasury company. MSTR is a high-beta Bitcoin capital-markets machine: the equity should be judged in sats/share, not dollars.',
    },
    'PYPL': {
        'category': 'Non-crypto real-business anchor',
        'why': 'Global digital payments infrastructure at a depressed valuation. PayPal is not a crypto beta stock; it is a mature money-movement network across roughly 200 markets with optionality in checkout, Venmo, and digital wallets.',
    },
    'RIOT': {
        'category': 'Bitcoin mining scale',
        'why': 'Vertically integrated Bitcoin miner with data-center upside. Riot combines mining, engineering, and large-scale data-center development, with the AI/HPC option layered on top.',
    },
    'SHM': {
        'category': 'Non-crypto real-business anchor',
        'why': 'The non-crypto quality anchor. Shimano is a century-old picks-and-shovels company for cycling and fishing: real products, real brand, global niche dominance.',
    },
    'STRC': {
        'category': 'Strategy credit stack',
        'why': 'Strategy credit exposure, not Strategy common equity. STRC is a variable-rate perpetual preferred designed to trade around $100 par and pay high cash dividends; the risk is Strategy\'s capital stack, not MSTR upside.',
    },
    'STRD': {
        'category': 'Strategy credit stack',
        'why': 'Long-duration high-yield Strategy preferred. STRD is a fixed 10% perpetual preferred: more income/security-stack exposure than upside participation.',
    },
    'WULF': {
        'category': 'AI/HPC power conversion',
        'why': 'Power-first AI/HPC infrastructure company. TeraWulf is a bet that scarce, scalable power sites become more valuable than the Bitcoin mining machines sitting on them.',
    },
    'CAN': {
        'category': 'High-risk mining-cycle option',
        'why': 'ASIC mining hardware call option. Canaan is one of the original Avalon ASIC miner makers; the turnaround thesis is mining hardware recovery plus self-mining/energy pivot, but it is much riskier than MSTR.',
    },
    '0XP': {
        'category': 'High-risk mining-cycle option',
        'why': 'Distressed legacy Bitcoin miner lottery ticket. Argo is not a core holding; it is a tiny survival/recovery option on a former UK-listed Bitcoin miner.',
    },
    '3M8': {
        'category': 'UK-listed Bitcoin treasury proxy',
        'why': 'UK-listed Bitcoin treasury proxy. The uniqueness is a small web-services company transformed into one of the UK\'s most visible Bitcoin treasury vehicles.',
    },
    'Y6G0': {
        'category': 'Ethereum treasury king',
        'why': 'The clearest public Ethereum treasury play. BitMine is trying to maximize ETH per share and become the institutional equity wrapper for Ethereum, staking, and the ETH monetary thesis.',
    },
}

STOCK_TARGETS = {
    'MSTR': {
        'target_price': Decimal('185.36'),
        'target_currency': 'USD',
        'target_date': '2027-01-30',
        'target_note': 'Target for the 12 new MSTR shares bought in late June: double the June 29, 2026 reference close within roughly seven months.',
        'target_quantity': Decimal('12'),
        'reference_price': Decimal('92.68'),
        'reference_date': '2026-06-29',
    },
}

TREASURY_STOCKS = {
    'metaplanet': {
        'name': 'Metaplanet',
        'ticker': 'DN3',
        'symbol': 'DN3.F',
        'benchmark_symbol': 'BTC-USD',
        'benchmark_name': 'Bitcoin',
        'benchmark_unit': 'BTC',
        'target_price': 250000,
        'target_label': 'Target to define',
        'target_multiple': None,
        'target_date': None,
        'start': '2024-01-01',
        'manager': {
            'name': 'Simon Gerovich',
            'role': 'Metaplanet',
            'image': 'img/gerovic.png',
        },
        'risk_rank': 2,
        'risk_label': 'Higher risk than MSTR: Japan-listed Bitcoin treasury with local market and liquidity risk.',
        'premium_label': 'BTC treasury re-rating',
        'baseline_note': 'Metaplanet is treated as a Bitcoin treasury equity with operating, jurisdiction, and Japan-market structure risk.',
        'thesis': 'Metaplanet is the closest non-US Bitcoin treasury analogue in this portfolio. The thesis is that it can compound BTC exposure through capital markets access, but the Japanese market introduces extra liquidity, governance, FX, and market-structure risks compared with MSTR.',
        'scenarios': [
            {'name': 'Tracks Bitcoin', 'multiple': 1.0},
            {'name': 'Treasury premium returns', 'multiple': 2.0},
            {'name': 'Japan re-rating', 'multiple': 4.0},
        ],
    },
    'asst': {
        'name': 'Asset Entities / Strive',
        'ticker': 'ASST',
        'symbol': 'ASST',
        'benchmark_symbol': 'BTC-USD',
        'benchmark_name': 'Bitcoin',
        'benchmark_unit': 'BTC',
        'target_price': 250000,
        'target_label': '15x by July 1, 2030',
        'target_multiple': 15.0,
        'target_date': '2030-07-01',
        'start': '2024-01-01',
        'manager': {
            'name': 'Matt Cole',
            'role': 'Strive',
            'image': 'img/cole.png',
        },
        'risk_rank': 3,
        'risk_label': 'Microcap treasury wrapper: smaller size means larger upside premium but materially higher execution risk.',
        'premium_label': 'Microcap BTC premium',
        'baseline_note': 'ASST demands a larger premium than Metaplanet because size and liquidity create more convexity and more fragility.',
        'thesis': 'ASST is treated as a smaller, higher-beta treasury stock. If the market rewards Bitcoin balance-sheet leverage, a smaller vehicle can re-rate harder than Metaplanet, but the same size advantage also makes drawdowns, dilution, and liquidity risk more severe.',
        'scenarios': [
            {'name': 'Tracks Bitcoin', 'multiple': 1.0},
            {'name': 'Small-cap premium', 'multiple': 3.0},
            {'name': 'Convex re-rating', 'multiple': 6.0},
            {'name': 'Extreme treasury premium', 'multiple': 10.0},
            {'name': 'Personal target', 'multiple': 15.0},
        ],
    },
    'bitmine': {
        'name': 'BitMine Immersion',
        'ticker': 'BMNR',
        'symbol': 'BMNR',
        'benchmark_symbol': 'ETH-USD',
        'benchmark_name': 'Ethereum',
        'benchmark_unit': 'ETH',
        'target_price': 25000,
        'target_label': '50x by July 1, 2031',
        'target_multiple': 50.0,
        'target_date': '2031-07-01',
        'start': '2024-01-01',
        'manager': {
            'name': 'Tom Lee',
            'role': 'BitMine Immersion',
            'image': 'img/tom_lee.png',
        },
        'risk_rank': 4,
        'risk_label': 'Highest risk in the treasury-stock sleeve: Ethereum treasury premium, operating risk, and more volatile market trust.',
        'premium_label': 'ETH treasury premium',
        'baseline_note': 'BitMine needs a very high target premium because Ethereum treasury equities demand a larger premium and carry more narrative and execution risk than Bitcoin treasury equities.',
        'thesis': 'BitMine is treated as the highest-beta treasury equity in this set. The target price assumptions should be aggressive because the market generally demands a larger premium for Ethereum-linked treasury exposure than for Bitcoin-linked balance-sheet exposure. This is not the fortress asset; it is the outer risk sleeve.',
        'scenarios': [
            {'name': 'Tracks Ethereum', 'multiple': 1.0},
            {'name': 'High premium returns', 'multiple': 5.0},
            {'name': 'ETH treasury mania', 'multiple': 10.0},
            {'name': 'Extreme premium', 'multiple': 20.0},
            {'name': 'Personal target', 'multiple': 50.0},
        ],
    },
}

MAY_2026_REPORT = {
    'date': '31.05.2026',
    'cash': Decimal('5976.43'),
    'bitcoin': Decimal('19285.36'),
    'stocks': Decimal('24489.50'),
    'bitcoin_amount': Decimal('0.39094743'),
}

PORTFOLIO_REPORT = {
    'date': '30.06.2026',
    'cash': Decimal('4698.22'),
    'bitcoin': Decimal('20446.87'),
    'stocks': Decimal('19595.66'),
    'bitcoin_amount': Decimal('0.42082719'),
    'notes': 'June close: IBKR NAV EUR 21,244.21 at EURCHF 0.9224; BTC 0.40968638 plus 1,114,081 sats at CoinGecko 30.06.2026 BTC/CHF; cash CHF 4,491.76 + CHF 160.34 + EUR 50.',
}

CURRENT_MONTH_TO_DATE_DEFAULT = {
    'cash': Decimal('7626.39'),
    'bitcoin': Decimal('21095.52'),
    'stocks': Decimal('19928.40'),
    'bitcoin_amount': Decimal('0.42082719'),
    'notes': 'Current month-to-date values entered on 02.08.2026: cash CHF 7,626.39, Bitcoin CHF 21,095.52, stocks CHF 19,928.40.',
}

PORTFOLIO_HISTORY = [
    {
        'date': '31.01.2024',
        'cash': Decimal('7110.21'),
        'bitcoin': Decimal('10851.60'),
        'stocks': Decimal('18142.41'),
        'bitcoin_amount': Decimal('0.2946247629551326'),
    },
    {
        'date': '29.02.2024',
        'cash': Decimal('2388.94'),
        'bitcoin': Decimal('12928.14'),
        'stocks': Decimal('20950.55'),
        'bitcoin_amount': Decimal('0.2397075677272512'),
    },
    {
        'date': '31.03.2024',
        'cash': Decimal('3386.41'),
        'bitcoin': Decimal('11357.49'),
        'stocks': Decimal('18728.13'),
        'bitcoin_amount': Decimal('0.1765335984382139'),
    },
    {
        'date': '30.04.2024',
        'cash': Decimal('6877.06'),
        'bitcoin': Decimal('12531.81'),
        'stocks': Decimal('18351.72'),
        'bitcoin_amount': Decimal('0.2247575441063611'),
    },
    {
        'date': '31.05.2024',
        'cash': Decimal('5615.86'),
        'bitcoin': Decimal('14284.10'),
        'stocks': Decimal('18997.96'),
        'bitcoin_amount': Decimal('0.2348517807444580'),
    },
    {
        'date': '30.06.2024',
        'cash': Decimal('2208.09'),
        'bitcoin': Decimal('18138.39'),
        'stocks': Decimal('15315.33'),
        'bitcoin_amount': Decimal('0.3214492187168093'),
    },
    {
        'date': '31.07.2024',
        'cash': Decimal('1900.96'),
        'bitcoin': Decimal('14823.17'),
        'stocks': Decimal('15062.26'),
        'bitcoin_amount': Decimal('0.2612268963536279'),
    },
    {
        'date': '31.08.2024',
        'cash': Decimal('1925.06'),
        'bitcoin': Decimal('17341.34'),
        'stocks': Decimal('11012.24'),
        'bitcoin_amount': Decimal('0.3466047341343739'),
    },
    {
        'date': '30.09.2024',
        'cash': Decimal('2734.18'),
        'bitcoin': Decimal('16948.10'),
        'stocks': Decimal('11518.24'),
        'bitcoin_amount': Decimal('0.3166081864515977'),
    },
    {
        'date': '31.10.2024',
        'cash': Decimal('1694.92'),
        'bitcoin': Decimal('20365.39'),
        'stocks': Decimal('12202.31'),
        'bitcoin_amount': Decimal('0.3355430997875829'),
    },
    {
        'date': '30.11.2024',
        'cash': Decimal('850.76'),
        'bitcoin': Decimal('26956.29'),
        'stocks': Decimal('22621.59'),
        'bitcoin_amount': Decimal('0.3172632643403502'),
    },
    {
        'date': '31.12.2024',
        'cash': Decimal('305.68'),
        'bitcoin': Decimal('30763.68'),
        'stocks': Decimal('19168.79'),
        'bitcoin_amount': Decimal('0.3625882315064564'),
    },
    {
        'date': '28.02.2025',
        'cash': Decimal('210.53'),
        'bitcoin': Decimal('28642.43'),
        'stocks': Decimal('15676.32'),
        'bitcoin_amount': Decimal('0.3766390831527100'),
    },
    {
        'date': '31.03.2025',
        'cash': Decimal('295.67'),
        'bitcoin': Decimal('21925.51'),
        'stocks': Decimal('13417.09'),
        'bitcoin_amount': Decimal('0.3005265492782613'),
    },
    {
        'date': '30.04.2025',
        'cash': Decimal('0.00'),
        'bitcoin': Decimal('21079.35'),
        'stocks': Decimal('13665.59'),
        'bitcoin_amount': Decimal('0.2708611526954541'),
    },
    {
        'date': '31.05.2025',
        'cash': Decimal('575.50'),
        'bitcoin': Decimal('23485.12'),
        'stocks': Decimal('13728.42'),
        'bitcoin_amount': Decimal('0.2723326450644974'),
    },
    {
        'date': '30.06.2025',
        'cash': Decimal('575.03'),
        'bitcoin': Decimal('23465.79'),
        'stocks': Decimal('13717.11'),
        'bitcoin_amount': Decimal('0.2762691679308987'),
    },
    {
        'date': '31.07.2025',
        'cash': Decimal('527.66'),
        'bitcoin': Decimal('26353.66'),
        'stocks': Decimal('15003.17'),
        'bitcoin_amount': Decimal('0.2797028679418128'),
    },
    {
        'date': '31.08.2025',
        'cash': Decimal('2215.88'),
        'bitcoin': Decimal('23378.65'),
        'stocks': Decimal('17594.47'),
        'bitcoin_amount': Decimal('0.2697982147065591'),
    },
    {
        'date': '30.09.2025',
        'cash': Decimal('8018.84'),
        'bitcoin': Decimal('25179.16'),
        'stocks': Decimal('22149.03'),
        'bitcoin_amount': Decimal('0.2771976212991545'),
    },
    {
        'date': '31.10.2025',
        'cash': Decimal('10726.08'),
        'bitcoin': Decimal('24234.97'),
        'stocks': Decimal('24488.53'),
        'bitcoin_amount': Decimal('0.2766214853458475'),
    },
    {
        'date': '30.11.2025',
        'cash': Decimal('10792.11'),
        'bitcoin': Decimal('24384.16'),
        'stocks': Decimal('24639.28'),
        'bitcoin_amount': Decimal('0.3353186521362005'),
    },
    {
        'date': '31.12.2025',
        'cash': Decimal('4183.23'),
        'bitcoin': Decimal('19637.38'),
        'stocks': Decimal('25608.66'),
        'bitcoin_amount': Decimal('0.2804621057210911'),
    },
    {
        'date': '31.01.2026',
        'cash': Decimal('3054.89'),
        'bitcoin': Decimal('18233.63'),
        'stocks': Decimal('15978.94'),
        'bitcoin_amount': Decimal('0.2804621057210911'),
    },
    {
        'date': '28.02.2026',
        'cash': Decimal('6473.79'),
        'bitcoin': Decimal('15999.41'),
        'stocks': Decimal('13270.44'),
        'bitcoin_amount': Decimal('0.31562533'),
    },
    {
        'date': '31.03.2026',
        'cash': Decimal('626.71'),
        'bitcoin': Decimal('16470.45'),
        'stocks': Decimal('15670.57'),
        'bitcoin_amount': Decimal('0.3041361'),
    },
    {
        'date': '30.04.2026',
        'coingecko_date': '30-04-2026',
        'cash': Decimal('4055.42'),
        'bitcoin': Decimal('18132.71'),
        'stocks': Decimal('22767.77'),
    },
    MAY_2026_REPORT,
    PORTFOLIO_REPORT,
]

DASHBOARD_USERNAME = os.environ.get('HASHEN_DASHBOARD_USERNAME', 'hashen')
DASHBOARD_PASSWORD = os.environ.get('HASHEN_DASHBOARD_PASSWORD', 'hashen123')


def require_dashboard_auth(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if getattr(settings, 'PUBLIC_SITE_ONLY', False):
            raise Http404
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Basic '):
            try:
                encoded = auth_header.split(' ', 1)[1].strip()
                decoded = base64.b64decode(encoded).decode('utf-8')
                username, password = decoded.split(':', 1)
                if (
                    compare_digest(username, DASHBOARD_USERNAME) and
                    compare_digest(password, DASHBOARD_PASSWORD)
                ):
                    return view_func(request, *args, **kwargs)
            except (ValueError, UnicodeDecodeError):
                pass
        response = HttpResponse('Authentication required', status=401)
        response['WWW-Authenticate'] = 'Basic realm="Hashen private dashboard"'
        return response
    return wrapped


def portfolio_total():
    return PORTFOLIO_REPORT['cash'] + PORTFOLIO_REPORT['bitcoin'] + PORTFOLIO_REPORT['stocks']


def period_total(period):
    return period['cash'] + period['bitcoin'] + period['stocks']


def parse_report_date(value):
    return datetime.strptime(value, '%d.%m.%Y').date()


def display_report_date(value):
    return value.strftime('%d.%m.%Y')


def month_end_for(value):
    last_day = calendar.monthrange(value.year, value.month)[1]
    return value.replace(day=last_day)


def previous_month_end(value):
    first_day = value.replace(day=1)
    return first_day - timedelta(days=1)


def decimal_from_request(value, default='0'):
    try:
        return Decimal(str(value).replace(',', '.'))
    except (InvalidOperation, AttributeError):
        return Decimal(default)


def static_period_map():
    periods = {}
    for period in PORTFOLIO_HISTORY:
        periods[parse_report_date(period['date'])] = dict(period)
    return periods


def snapshot_to_period(snapshot):
    period = {
        'date': display_report_date(snapshot.snapshot_date),
        'cash': snapshot.cash_chf,
        'bitcoin': snapshot.bitcoin_chf,
        'stocks': snapshot.stocks_chf,
    }
    if snapshot.bitcoin_amount:
        period['bitcoin_amount'] = snapshot.bitcoin_amount
    if snapshot.notes:
        period['notes'] = snapshot.notes
    return period


def locked_portfolio_periods():
    periods = static_period_map()
    for snapshot in PortfolioSnapshot.objects.filter(locked=True):
        periods[snapshot.snapshot_date] = snapshot_to_period(snapshot)
    return [periods[date] for date in sorted(periods)]


def latest_locked_period():
    periods = locked_portfolio_periods()
    return periods[-1]


def get_pending_month_end_snapshot(today=None, current_snapshot=None):
    today = today or django_timezone.localdate()
    locked_period = latest_locked_period()
    locked_date = parse_report_date(locked_period['date'])
    pending_date = previous_month_end(today)
    if pending_date <= locked_date:
        return None

    snapshot = PortfolioSnapshot.objects.filter(snapshot_date=pending_date).first()
    if snapshot:
        return snapshot

    current_snapshot = current_snapshot or get_current_portfolio_snapshot()
    return PortfolioSnapshot.objects.create(
        snapshot_date=pending_date,
        cash_chf=current_snapshot.cash_chf,
        bitcoin_chf=current_snapshot.bitcoin_chf,
        stocks_chf=current_snapshot.stocks_chf,
        bitcoin_amount=current_snapshot.bitcoin_amount,
        locked=False,
        notes='Pending month-end close copied from the latest saved working values.',
    )


def portfolio_periods_with_pending_month_end():
    periods = static_period_map()
    for snapshot in PortfolioSnapshot.objects.filter(locked=True):
        periods[snapshot.snapshot_date] = snapshot_to_period(snapshot)

    pending_snapshot = get_pending_month_end_snapshot()
    if pending_snapshot:
        periods[pending_snapshot.snapshot_date] = snapshot_to_period(pending_snapshot)

    return [periods[date] for date in sorted(periods)]


def initial_current_snapshot_values(today=None):
    today = today or django_timezone.localdate()
    current_end = month_end_for(today)
    if current_end == datetime(2026, 8, 31).date():
        return CURRENT_MONTH_TO_DATE_DEFAULT

    locked = latest_locked_period()
    return {
        'cash': locked['cash'],
        'bitcoin': locked['bitcoin'],
        'stocks': locked['stocks'],
        'bitcoin_amount': locked.get('bitcoin_amount'),
        'notes': 'Seeded from the latest month-end close until current values are entered.',
    }


def get_current_portfolio_snapshot():
    today = django_timezone.localdate()
    current_end = month_end_for(today)
    snapshot = PortfolioSnapshot.objects.filter(snapshot_date=current_end).first()
    if snapshot:
        return snapshot

    initial = initial_current_snapshot_values(today)
    return PortfolioSnapshot.objects.create(
        snapshot_date=current_end,
        cash_chf=initial['cash'],
        bitcoin_chf=initial['bitcoin'],
        stocks_chf=initial['stocks'],
        bitcoin_amount=initial.get('bitcoin_amount'),
        locked=False,
        notes=initial.get('notes', ''),
    )


def serialize_snapshot(snapshot):
    return {
        'date': snapshot.snapshot_date.isoformat(),
        'date_label': display_report_date(snapshot.snapshot_date),
        'cash_chf': float(snapshot.cash_chf),
        'bitcoin_chf': float(snapshot.bitcoin_chf),
        'stocks_chf': float(snapshot.stocks_chf),
        'bitcoin_amount': float(snapshot.bitcoin_amount) if snapshot.bitcoin_amount else None,
        'total_chf': float(snapshot.total_chf),
        'locked': snapshot.locked,
        'notes': snapshot.notes,
        'updated_at': snapshot.updated_at.isoformat() if snapshot.updated_at else None,
    }


def serialize_period(period, locked=True):
    return {
        'date': parse_report_date(period['date']).isoformat(),
        'date_label': period['date'],
        'cash_chf': float(period['cash']),
        'bitcoin_chf': float(period['bitcoin']),
        'stocks_chf': float(period['stocks']),
        'total_chf': float(period_total(period)),
        'bitcoin_amount': float(period['bitcoin_amount']) if period.get('bitcoin_amount') else None,
        'locked': locked,
    }


def report_period_rows(include_pending=True):
    rows = {}
    for period in PORTFOLIO_HISTORY:
        date_obj = parse_report_date(period['date'])
        rows[date_obj] = {
            'date': date_obj,
            'period': dict(period),
            'locked': True,
        }

    for snapshot in PortfolioSnapshot.objects.filter(locked=True):
        rows[snapshot.snapshot_date] = {
            'date': snapshot.snapshot_date,
            'period': snapshot_to_period(snapshot),
            'locked': True,
        }

    if include_pending:
        pending_snapshot = get_pending_month_end_snapshot()
        if pending_snapshot:
            rows[pending_snapshot.snapshot_date] = {
                'date': pending_snapshot.snapshot_date,
                'period': snapshot_to_period(pending_snapshot),
                'locked': pending_snapshot.locked,
            }

    return [rows[date] for date in sorted(rows)]


def quarter_label(value):
    return 'Q%s %s' % (((value.month - 1) // 3) + 1, value.year)


def asset_report_rows(start_period, end_period):
    start_total = period_total(start_period)
    end_total = period_total(end_period)
    rows = []
    for key, label in (('cash', 'Cash'), ('bitcoin', 'Bitcoin'), ('stocks', 'Stocks')):
        start_value = start_period[key]
        end_value = end_period[key]
        start_weight = start_value / start_total * Decimal('100') if start_total else Decimal('0')
        end_weight = end_value / end_total * Decimal('100') if end_total else Decimal('0')
        rows.append({
            'key': key,
            'label': label,
            'value': end_value,
            'value_change': end_value - start_value,
            'weight': end_weight,
            'weight_change': end_weight - start_weight,
        })
    return rows


def quote_history_at_or_before(holding, date_obj):
    return StockQuoteHistory.objects.filter(
        ticker=normalize_ticker(holding['ticker']),
        symbol=(holding['symbol'] or '').strip().upper(),
        quote_date__lte=date_obj,
    ).order_by('-quote_date').first()


def latest_saved_quote_for_report(holding):
    return _saved_quote(holding['ticker'], holding['symbol'])


def report_price_point(holding, date_obj, use_latest_saved=False, allow_baseline=True):
    historical = quote_history_at_or_before(holding, date_obj)
    if historical:
        return historical.price, historical.currency, 'saved %s' % display_report_date(historical.quote_date)

    if use_latest_saved:
        saved = latest_saved_quote_for_report(holding)
        if saved:
            return saved.price, saved.currency, 'latest saved %s' % display_report_date(django_timezone.localtime(saved.updated_at).date())

    if not allow_baseline:
        return None, None, 'unavailable'

    reference_price = holding.get('reference_price') or holding['average_price']
    reference_currency = holding.get('cost_currency') or holding.get('fallback_currency') or 'USD'
    if reference_price:
        return reference_price, reference_currency, 'average cost baseline'

    if holding.get('fallback_value') and holding.get('shares'):
        return holding['fallback_value'] / holding['shares'], holding.get('fallback_currency') or reference_currency, 'fallback baseline'

    return None, None, 'unavailable'


def stock_movers_for_report(start_date, end_date, latest_report_date=None):
    movers = []
    use_latest_saved = latest_report_date is not None and end_date == latest_report_date
    for holding in configured_stock_holdings():
        start_price, start_currency, start_source = report_price_point(holding, start_date)
        end_price, end_currency, end_source = report_price_point(
            holding,
            end_date,
            use_latest_saved=use_latest_saved,
            allow_baseline=False,
        )
        if not start_price or not end_price or start_currency != end_currency:
            continue
        change_pct = (end_price - start_price) / start_price * Decimal('100') if start_price else Decimal('0')
        movers.append({
            'ticker': holding['ticker'],
            'name': holding['name'],
            'start_price': start_price,
            'end_price': end_price,
            'currency': end_currency,
            'change_pct': change_pct,
            'start_source': start_source,
            'end_source': end_source,
        })

    ordered = sorted(movers, key=lambda item: item['change_pct'], reverse=True)
    return ordered[:5], ordered[-5:][::-1]


def build_period_report(kind, start_row, end_row, latest_report_date=None):
    start_period = start_row['period']
    end_period = end_row['period']
    start_date = start_row['date']
    end_date = end_row['date']
    beginning_nav = period_total(start_period)
    ending_nav = period_total(end_period)
    winners, losers = stock_movers_for_report(start_date, end_date, latest_report_date=latest_report_date)
    label = display_report_date(end_date)
    if kind == 'quarterly':
        label = quarter_label(end_date)
    elif kind == 'yearly':
        label = str(end_date.year)

    return {
        'kind': kind,
        'label': label,
        'date': end_date,
        'date_iso': end_date.isoformat(),
        'date_label': display_report_date(end_date),
        'start_date': start_date,
        'start_date_label': display_report_date(start_date),
        'beginning_nav': beginning_nav,
        'ending_nav': ending_nav,
        'change_nav': ending_nav - beginning_nav,
        'change_pct': (ending_nav - beginning_nav) / beginning_nav * Decimal('100') if beginning_nav else Decimal('0'),
        'asset_rows': asset_report_rows(start_period, end_period),
        'winners': winners,
        'losers': losers,
        'locked': end_row['locked'],
    }


def generated_portfolio_reports():
    rows = report_period_rows(include_pending=True)
    reports = {
        'monthly': [],
        'quarterly': [],
        'yearly': [],
    }
    by_date = {row['date']: row for row in rows}
    sorted_rows = rows
    latest_report_date = sorted_rows[-1]['date'] if sorted_rows else None

    for index, row in enumerate(sorted_rows[1:], 1):
        reports['monthly'].append(build_period_report('monthly', sorted_rows[index - 1], row, latest_report_date=latest_report_date))

    for row in sorted_rows:
        date_obj = row['date']
        if date_obj.month not in (3, 6, 9, 12):
            continue
        previous_quarter_month = date_obj.month - 3
        previous_year = date_obj.year
        if previous_quarter_month <= 0:
            previous_quarter_month += 12
            previous_year -= 1
        previous_quarter_end = datetime(
            previous_year,
            previous_quarter_month,
            calendar.monthrange(previous_year, previous_quarter_month)[1],
        ).date()
        if previous_quarter_end in by_date:
            reports['quarterly'].append(build_period_report('quarterly', by_date[previous_quarter_end], row, latest_report_date=latest_report_date))

        if date_obj.month == 12:
            previous_year_end = datetime(date_obj.year - 1, 12, 31).date()
            if previous_year_end in by_date:
                reports['yearly'].append(build_period_report('yearly', by_date[previous_year_end], row, latest_report_date=latest_report_date))

    for kind in reports:
        reports[kind].sort(key=lambda report: report['date'], reverse=True)
    return reports


def find_generated_report(kind, date_iso):
    reports = generated_portfolio_reports().get(kind, [])
    for report in reports:
        if report['date_iso'] == date_iso:
            return report
    raise Http404('Report not found')


def format_money(value, currency='CHF'):
    return "%s %s" % (currency, "{:,.2f}".format(value).replace(",", "'"))


def format_pct(value):
    return "%.2f%%" % value


def chf(value):
    return "CHF {:,.2f}".format(value).replace(",", "'")


def pdf_escape(value):
    return str(value).replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def build_simple_pdf(lines):
    content_lines = ['BT', '/F1 11 Tf', '50 790 Td', '16 TL']
    for line in lines:
        content_lines.append('(%s) Tj' % pdf_escape(line))
        content_lines.append('T*')
    content_lines.append('ET')
    stream = '\n'.join(content_lines).encode('latin-1', 'replace')
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length %d >>\nstream\n%s\nendstream' % (len(stream), stream),
    ]
    pdf = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(b'%d 0 obj\n' % index)
        pdf.extend(obj)
        pdf.extend(b'\nendobj\n')
    xref_offset = len(pdf)
    pdf.extend(b'xref\n0 %d\n' % (len(objects) + 1))
    pdf.extend(b'0000000000 65535 f \n')
    for offset in offsets[1:]:
        pdf.extend(b'%010d 00000 n \n' % offset)
    pdf.extend(b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref_offset))
    return bytes(pdf)


def get_default_newsletter():
    newsletter = Newsletter.objects.first()
    if newsletter:
        return newsletter
    return Newsletter.objects.create(
        title='Hashen',
        slug='daily-news',
        email='contact@hashen.finance',
        sender='Hashen',
    )


def privacy_policy(request):
    return render(request, 'blog/privacy.html')

def contact_view(request):
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Thanks for contacting us!")
            return redirect('index')  # Redirect to a success page.
        else:
            print(form.errors)
    # else:
    #     form = ContactForm()
    
    # return render(request, 'base1.html', {'form': form})



@login_required
def resources_view(request):
    resources = Resource.objects.all().order_by('-created_at')  # Assuming you want the newest resources first
    return render(request, 'blog/resources.html', {'resources': resources})



@login_required
def dashboard(request):
    # Fetch the posts by the current user
    user_posts = Post.objects.filter(author=request.user).order_by('-date_posted')

    # Fetch comments on the user's posts
    user_comments = Comment.objects.filter(post__author=request.user).order_by('-created_at')

    # You can add more context as per your application's functionality
    context = {
        'title': 'Dashboard',
        'user_posts': user_posts,
        'user_comments': user_comments
    }

    return render(request, 'blog/dashboard.html', context)

class PostListView(ListView):
    model = Post
    template_name = 'blog/blog.html'
    context_object_name = 'posts'
    paginate_by = 5

    def get_queryset(self):
        try:
            keyword = self.request.GET['q']
        except:
            keyword = ''
        if (keyword != ''):
            object_list = self.model.objects.filter(
                Q(content__icontains=keyword) | Q(title__icontains=keyword))
        else:
            object_list = self.model.objects.all()
        return object_list


class UserPostListView(ListView):
    model = Post
    template_name = 'blog/user_posts.html'
    context_object_name = 'posts'
    paginate_by = 5

    def get_queryset(self):
        user = get_object_or_404(User, username=self.kwargs.get('username'))
        return Post.objects.filter(author=user).order_by('-date_posted')


class PostDetailView(DetailView):
    model = Post


class PostCreateView(LoginRequiredMixin, CreateView):
    model = Post
    form_class = PostForm

    def form_valid(self, form):
        form.instance.author = self.request.user
        return super().form_valid(form)


class PostUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Post
    fields = ['title', 'content']

    def form_valid(self, form):
        form.instance.author = self.request.user
        return super().form_valid(form)

    def test_func(self):
        post = self.get_object()
        if self.request.user == post.author:
            return True
        return False


class PostDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = Post
    success_url = '/'

    def test_func(self):
        post = self.get_object()
        if self.request.user == post.author:
            return True
        return False


def about(request):
    return render(request, 'blog/about.html', {'title': 'About'})

def bitcoin(request):
    return render(request, 'blog/bitcoin.html', {'title': 'Bitcoin'})

def blog(request):
        return render(request, 'blog/blog.html', {'title': 'Blog'})

def index(request):
    newsletter = get_default_newsletter()
    return render(request, 'blog/index.html', {'title': 'Index', 'newsletter':newsletter})


def clean_lines(value):
    return [line.strip() for line in (value or '').splitlines() if line.strip()]


def serialize_memo_note(note):
    return {
        'slug': note.slug,
        'title': note.title,
        'subtitle': note.subtitle or note.position_note[:140],
        'date': note.created_at.strftime('%B %-d, %Y'),
        'asset': note.asset or 'Private note',
        'price_label': note.price_label or 'Reference',
        'price_value': note.price_value or 'Not set',
        'price_source': 'User note',
        'source_url': '',
        'position_note': note.position_note,
        'horizon': note.horizon or 'Open',
        'exit_note': note.exit_note or 'No exit plan recorded yet.',
        'thesis': clean_lines(note.thesis) or [note.position_note],
        'guardrails': clean_lines(note.guardrails) or ['No guardrails recorded yet.'],
        'tags': [tag.strip() for tag in note.tags.split(',') if tag.strip()],
        'is_user_note': True,
    }


def unique_memo_slug(title):
    base_slug = slugify(title)[:190] or 'memo-note'
    slug = base_slug
    counter = 2
    while MemoNote.objects.filter(slug=slug).exists() or any(memo['slug'] == slug for memo in MEMOS):
        suffix = '-%s' % counter
        slug = '%s%s' % (base_slug[:220 - len(suffix)], suffix)
        counter += 1
    return slug


def get_memo(slug):
    for memo in MEMOS:
        if memo['slug'] == slug:
            return memo
    try:
        return serialize_memo_note(MemoNote.objects.get(slug=slug))
    except MemoNote.DoesNotExist:
        pass
    raise Http404('Memo not found')


@require_dashboard_auth
def memos(request):
    user_memos = [serialize_memo_note(note) for note in MemoNote.objects.all()]
    return render(request, 'blog/memos.html', {
        'title': 'Memos',
        'memos': user_memos + MEMOS,
    })


@require_dashboard_auth
def memo_detail(request, slug):
    memo = get_memo(slug)
    return render(request, 'blog/memo_detail.html', {
        'title': memo['title'],
        'memo': memo,
    })


@require_dashboard_auth
def add_memo_note(request):
    if request.method != 'POST':
        return redirect('memos')

    title = (request.POST.get('title') or '').strip()
    position_note = (request.POST.get('position_note') or '').strip()

    if not title or not position_note:
        messages.error(request, 'Add a title and note before saving.')
        return redirect('memos')

    note = MemoNote.objects.create(
        title=title,
        slug=unique_memo_slug(title),
        subtitle=(request.POST.get('subtitle') or '').strip(),
        asset=(request.POST.get('asset') or '').strip(),
        horizon=(request.POST.get('horizon') or '').strip(),
        price_label=(request.POST.get('price_label') or '').strip(),
        price_value=(request.POST.get('price_value') or '').strip(),
        position_note=position_note,
        exit_note=(request.POST.get('exit_note') or '').strip(),
        thesis=(request.POST.get('thesis') or '').strip(),
        guardrails=(request.POST.get('guardrails') or '').strip(),
        tags=(request.POST.get('tags') or '').strip(),
    )
    messages.success(request, 'Memo note saved.')
    return redirect('memo_detail', slug=note.slug)


@ensure_csrf_cookie
@require_dashboard_auth
def dashboard(request):
    return render(request, 'blog/dashboard.html', {'title': 'Dashboard'})


@require_dashboard_auth
def mstr_dashboard(request):
    return render(request, 'blog/mstr_dashboard.html', {'title': 'MSTR'})


@require_dashboard_auth
def stocks_dashboard(request):
    return render(request, 'blog/stocks_dashboard.html', {'title': 'Stocks'})


@require_dashboard_auth
def add_stock_holding(request):
    if request.method != 'POST':
        return redirect('stocks_dashboard')

    try:
        ticker = normalize_ticker(request.POST.get('ticker'))
        symbol = (request.POST.get('symbol') or ticker).strip().upper()
        name = (request.POST.get('name') or ticker).strip()
        shares = parse_decimal(request.POST.get('shares'), Decimal('0'))
        average_price = parse_decimal(request.POST.get('average_price'), Decimal('0'))
        cost_currency = normalize_ticker(request.POST.get('cost_currency') or 'USD')[:3]
        bought_at = parse_datetime_local(request.POST.get('bought_at')) or django_timezone.now()
        target_price = parse_decimal(request.POST.get('target_price'))
        target_date = parse_date(request.POST.get('target_date'))
        target_currency = normalize_ticker(request.POST.get('target_currency') or cost_currency)[:3]
        fallback_value = shares * average_price

        if not ticker or not symbol or shares <= 0 or average_price <= 0:
            raise ValueError('Ticker, symbol, shares, and average price are required.')

        StockHolding.objects.create(
            name=name,
            ticker=ticker,
            symbol=symbol,
            shares=shares,
            average_price=average_price,
            cost_currency=cost_currency,
            bought_at=bought_at,
            fallback_value=fallback_value,
            fallback_currency=cost_currency,
            category=(request.POST.get('category') or '').strip(),
            why_own=(request.POST.get('why_own') or '').strip(),
            target_price=target_price,
            target_currency=target_currency,
            target_date=target_date,
            target_note=(request.POST.get('target_note') or '').strip(),
        )
        return redirect('stock_holding_detail', ticker=ticker.lower())
    except (InvalidOperation, ValueError):
        return redirect('stocks_dashboard')


@require_dashboard_auth
def stock_holding_detail(request, ticker):
    holding = find_stock_holding(ticker)
    error = None
    try:
        quote, quote_status, quote_error = _quote_for_symbol(holding['ticker'], holding['symbol'], auto_refresh=True)
        price = quote['price']
        currency = quote['currency']
        live = quote_status == 'live'
        error = quote_error
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        price = holding['fallback_value'] / holding['shares']
        currency = holding['fallback_currency']
        live = False
        error = str(exc)

    value = price * holding['shares']
    cost_value = holding['shares'] * holding['average_price']
    target_price = holding.get('target_price')
    target_quantity = holding.get('target_quantity') or holding['shares']
    target_value = target_price * target_quantity if target_price else None
    target_upside_pct = None
    if target_price and price and (holding.get('target_currency') or currency) == currency:
        target_upside_pct = (target_price - price) / price * Decimal('100')

    context = {
        'title': holding['ticker'],
        'holding': holding,
        'price': price,
        'currency': currency,
        'value': value,
        'cost_value': cost_value,
        'target_value': target_value,
        'target_quantity': target_quantity,
        'target_upside_pct': target_upside_pct,
        'live': live,
        'error': error,
    }
    return render(request, 'blog/stock_holding_detail.html', context)


@require_dashboard_auth
def treasury_stock_dashboard(request, slug):
    config = TREASURY_STOCKS.get(slug)
    if not config:
        return redirect('stocks_dashboard')
    context = {
        'title': config['name'],
        'stock': config,
        'stock_json': json.dumps(config),
        'slug': slug,
        'treasury_stocks': TREASURY_STOCKS,
    }
    return render(request, 'blog/treasury_stock_dashboard.html', context)


def get_historical_bitcoin_chf(date):
    params = parse.urlencode({
        'date': date,
        'localization': 'false',
    })
    url = 'https://api.coingecko.com/api/v3/coins/bitcoin/history?%s' % params
    with urlrequest.urlopen(url, timeout=8) as response:
        data = json.loads(response.read().decode('utf-8'))
    return Decimal(str(data['market_data']['current_price']['chf']))


@require_dashboard_auth
def wealth_progression(request):
    periods = []
    source_periods = portfolio_periods_with_pending_month_end()
    for period in source_periods:
        historical_price = None
        btc_amount = None
        if period.get('bitcoin_amount'):
            btc_amount = period['bitcoin_amount']
        elif period.get('coingecko_date'):
            try:
                historical_price = get_historical_bitcoin_chf(period['coingecko_date'])
                btc_amount = period['bitcoin'] / historical_price
            except (HTTPError, URLError, TimeoutError, KeyError, json.JSONDecodeError, InvalidOperation):
                historical_price = None
                btc_amount = None
        periods.append({
            'date': period['date'],
            'cash_chf': float(period['cash']),
            'bitcoin_chf': float(period['bitcoin']),
            'stocks_chf': float(period['stocks']),
            'total_chf': float(period_total(period)),
            'bitcoin_price_chf': float(historical_price) if historical_price else None,
            'bitcoin_amount': float(btc_amount) if btc_amount else None,
        })

    first_total = period_total(source_periods[0])
    latest_total = period_total(source_periods[-1])
    return JsonResponse({
        'status': 'ok',
        'source': 'CoinGecko',
        'source_url': 'https://docs.coingecko.com/reference/coins-id-history',
        'periods': periods,
        'change_chf': float(latest_total - first_total),
        'change_pct': float((latest_total - first_total) / first_total * Decimal('100')),
    })


@require_dashboard_auth
def portfolio_snapshot(request):
    if request.method == 'GET':
        current_snapshot = get_current_portfolio_snapshot()
        locked_period = latest_locked_period()
        locked_date = parse_report_date(locked_period['date'])
        pending_snapshot = get_pending_month_end_snapshot(current_snapshot=current_snapshot)
        pending_date = previous_month_end(django_timezone.localdate())
        pending_month_end = pending_date > locked_date
        latest_period = snapshot_to_period(pending_snapshot) if pending_snapshot else locked_period
        return JsonResponse({
            'status': 'ok',
            'current': serialize_snapshot(current_snapshot),
            'latest_locked': serialize_period(locked_period, locked=True),
            'latest_month_end': serialize_period(latest_period, locked=pending_snapshot is None or pending_snapshot.locked),
            'pending_month_end': pending_month_end,
            'pending_month_end_date': pending_date.isoformat(),
            'pending_month_end_label': display_report_date(pending_date),
        })

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'error': 'Unsupported method'}, status=405)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'error': 'Invalid JSON'}, status=400)

    action = payload.get('action', 'save_current')
    today = django_timezone.localdate()
    snapshot_date = month_end_for(today)
    locked = False

    if action == 'lock_month_end':
        date_value = payload.get('snapshot_date')
        try:
            snapshot_date = datetime.strptime(date_value, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            snapshot_date = previous_month_end(today)
        locked = True
    elif action != 'save_current':
        return JsonResponse({'status': 'error', 'error': 'Unknown action'}, status=400)

    bitcoin_amount = payload.get('bitcoin_amount')
    snapshot, _created = PortfolioSnapshot.objects.update_or_create(
        snapshot_date=snapshot_date,
        defaults={
            'cash_chf': decimal_from_request(payload.get('cash_chf')).quantize(Decimal('0.01')),
            'bitcoin_chf': decimal_from_request(payload.get('bitcoin_chf')).quantize(Decimal('0.01')),
            'stocks_chf': decimal_from_request(payload.get('stocks_chf')).quantize(Decimal('0.01')),
            'bitcoin_amount': decimal_from_request(bitcoin_amount).quantize(Decimal('0.00000001')) if bitcoin_amount not in (None, '') else None,
            'locked': locked,
            'notes': (payload.get('notes') or '').strip(),
        }
    )
    return JsonResponse({
        'status': 'ok',
        'snapshot': serialize_snapshot(snapshot),
    })


@require_dashboard_auth
def portfolio_reports(request):
    reports = generated_portfolio_reports()
    latest_monthly = reports['monthly'][0] if reports['monthly'] else None
    has_new_report = bool(latest_monthly and not latest_monthly['locked'])
    context = {
        'title': 'Reports',
        'reports': reports,
        'latest_monthly': latest_monthly,
        'has_new_report': has_new_report,
        'money': format_money,
        'pct': format_pct,
    }
    return render(request, 'blog/portfolio_reports.html', context)


def report_pdf_lines(report):
    lines = [
        'Hashen - Portfolio Report',
        'Report type: %s' % report['kind'].title(),
        'Period: %s to %s' % (report['start_date_label'], report['date_label']),
        'Status: %s' % ('Final' if report['locked'] else 'New report available - pending lock'),
        '',
        'NAV',
        'Beginning NAV: %s' % chf(report['beginning_nav']),
        'Ending NAV: %s' % chf(report['ending_nav']),
        'Change: %s / %s' % (chf(report['change_nav']), format_pct(report['change_pct'])),
        '',
        'Portfolio summary and asset allocation',
    ]
    for row in report['asset_rows']:
        lines.append(
            '%s: %s (%s), %s (%s)' % (
                row['label'],
                chf(row['value']),
                chf(row['value_change']),
                format_pct(row['weight']),
                format_pct(row['weight_change']),
            )
        )
    lines.extend([
        '',
        'Five biggest stock winners by percentage gain',
    ])
    if report['winners']:
        for mover in report['winners']:
            lines.append('%s: %s' % (mover['ticker'], format_pct(mover['change_pct'])))
    else:
        lines.append('Unavailable until saved quote history exists.')
    lines.extend([
        '',
        'Five biggest stock losers by percentage loss',
    ])
    if report['losers']:
        for mover in report['losers']:
            lines.append('%s: %s' % (mover['ticker'], format_pct(mover['change_pct'])))
    else:
        lines.append('Unavailable until saved quote history exists.')
    lines.extend([
        '',
        'Notes',
        'Values are shown in CHF unless an individual stock price currency is shown.',
        'Stock movers use saved quote history where available and average-cost baseline otherwise.',
    ])
    return lines


@require_dashboard_auth
def portfolio_period_report_pdf(request, kind, date):
    if kind not in ('monthly', 'quarterly', 'yearly'):
        raise Http404('Report type not found')
    report = find_generated_report(kind, date)
    lines = report_pdf_lines(report)
    response = HttpResponse(build_simple_pdf(lines), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="hashen-%s-report-%s.pdf"' % (kind, report['date_iso'])
    return response


@require_dashboard_auth
def portfolio_report_pdf(request):
    reports = generated_portfolio_reports()
    if not reports['monthly']:
        raise Http404('Report not found')
    report = reports['monthly'][0]
    lines = report_pdf_lines(report)
    response = HttpResponse(build_simple_pdf(lines), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="hashen-monthly-report-%s.pdf"' % report['date_iso']
    return response


def bitcoin_price(request):
    currencies = request.GET.get('currencies', 'chf,usd,eur,gbp').lower()
    allowed_currencies = {'chf', 'usd', 'eur', 'gbp'}
    selected_currencies = [
        currency for currency in currencies.split(',')
        if currency in allowed_currencies
    ] or ['chf']
    params = parse.urlencode({
        'ids': 'bitcoin',
        'vs_currencies': ','.join(selected_currencies),
        'include_24hr_change': 'true',
        'include_last_updated_at': 'true',
        'precision': 'full',
    })
    url = 'https://api.coingecko.com/api/v3/simple/price?%s' % params
    market_url = 'https://api.coingecko.com/api/v3/coins/markets?%s' % parse.urlencode({
        'vs_currency': 'chf',
        'ids': 'bitcoin',
        'precision': 'full',
    })

    try:
        with urlrequest.urlopen(url, timeout=6) as response:
            data = json.loads(response.read().decode('utf-8'))
        market_data = {}
        try:
            with urlrequest.urlopen(market_url, timeout=6) as response:
                market = json.loads(response.read().decode('utf-8'))
            if market:
                market_data = {
                    'ath_chf': market[0].get('ath'),
                    'ath_date': market[0].get('ath_date'),
                    'ath_change_percentage': market[0].get('ath_change_percentage'),
                }
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, IndexError, KeyError):
            market_data = {}
        return JsonResponse({
            'source': 'CoinGecko',
            'source_url': 'https://docs.coingecko.com/reference/simple-price',
            'status': 'live',
            'data': data,
            'market': market_data,
        })
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return JsonResponse({
            'source': 'CoinGecko',
            'source_url': 'https://docs.coingecko.com/reference/simple-price',
            'status': 'unavailable',
            'data': {
                'bitcoin': {
                    'chf': None,
                    'usd': None,
                    'eur': None,
                    'gbp': None,
                    'last_updated_at': None,
                    'chf_24h_change': None,
                    'usd_24h_change': None,
                    'eur_24h_change': None,
                    'gbp_24h_change': None,
                }
            },
            'market': {},
        }, status=503)


def _unix_date(value):
    parsed = datetime.strptime(value, '%Y-%m-%d')
    return int(parsed.replace(tzinfo=timezone.utc).timestamp())


def _fetch_yahoo_daily_series(symbol, start):
    period1 = _unix_date(start)
    period2 = int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp())
    params = parse.urlencode({
        'period1': period1,
        'period2': period2,
        'interval': '1d',
        'events': 'history',
        'includeAdjustedClose': 'true',
    })
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/%s?%s' % (parse.quote(symbol), params)
    req = urlrequest.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urlrequest.urlopen(req, timeout=8) as response:
        payload = json.loads(response.read().decode('utf-8'))

    result = payload['chart']['result'][0]
    timestamps = result.get('timestamp') or []
    quote = result['indicators']['quote'][0]
    closes = quote.get('close') or []
    adjusted = result.get('indicators', {}).get('adjclose', [{}])[0].get('adjclose') or closes
    points = []
    for timestamp, close in zip(timestamps, adjusted):
        if close is None:
            continue
        points.append({
            'date': datetime.fromtimestamp(timestamp, tz=timezone.utc).date(),
            'close': float(close),
        })
    if not points:
        raise ValueError('No Yahoo Finance data returned for %s' % symbol)
    return points


def _month_end_points(points):
    months = {}
    for point in points:
        months[point['date'].strftime('%Y-%m')] = point
    return months


def _fetch_yahoo_quote(symbol):
    params = parse.urlencode({
        'range': '1d',
        'interval': '1m',
    })
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/%s?%s' % (parse.quote(symbol), params)
    req = urlrequest.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urlrequest.urlopen(req, timeout=8) as response:
        payload = json.loads(response.read().decode('utf-8'))
    result = payload['chart']['result'][0]
    meta = result.get('meta', {})
    quote = result.get('indicators', {}).get('quote', [{}])[0]
    closes = [price for price in quote.get('close', []) if price is not None]
    price = meta.get('regularMarketPrice') or meta.get('previousClose') or (closes[-1] if closes else None)
    if price is None:
        raise ValueError('No price returned for %s' % symbol)
    return {
        'price': Decimal(str(price)),
        'currency': (meta.get('currency') or 'USD').upper(),
        'exchange': meta.get('exchangeName') or meta.get('fullExchangeName') or '',
        'time': meta.get('regularMarketTime'),
    }


def _quote_market_datetime(timestamp):
    if not timestamp:
        return None
    try:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _saved_quote(ticker, symbol):
    return StockQuoteSnapshot.objects.filter(
        ticker=normalize_ticker(ticker),
        symbol=(symbol or '').strip().upper(),
    ).first()


def _quote_is_stale(snapshot):
    if not snapshot or not snapshot.updated_at:
        return True
    return django_timezone.now() - snapshot.updated_at > STOCK_QUOTE_STALE_AFTER


def _save_quote_snapshot(ticker, symbol, quote):
    normalized_ticker = normalize_ticker(ticker)
    normalized_symbol = (symbol or '').strip().upper()
    snapshot, _created = StockQuoteSnapshot.objects.update_or_create(
        ticker=normalized_ticker,
        symbol=normalized_symbol,
        defaults={
            'price': quote['price'].quantize(Decimal('0.000001')),
            'currency': quote['currency'],
            'exchange': quote.get('exchange', ''),
            'market_time': _quote_market_datetime(quote.get('time')),
            'source': 'Yahoo Finance',
        }
    )
    StockQuoteHistory.objects.update_or_create(
        ticker=normalized_ticker,
        symbol=normalized_symbol,
        quote_date=django_timezone.localdate(),
        defaults={
            'price': quote['price'].quantize(Decimal('0.000001')),
            'currency': quote['currency'],
            'source': 'Yahoo Finance',
        }
    )
    return snapshot


def _snapshot_to_quote(snapshot):
    return {
        'price': snapshot.price,
        'currency': snapshot.currency,
        'exchange': snapshot.exchange,
        'time': snapshot.market_time,
    }


def _quote_for_symbol(ticker, symbol, force_refresh=False, auto_refresh=True):
    snapshot = _saved_quote(ticker, symbol)
    should_refresh = force_refresh or (auto_refresh and _quote_is_stale(snapshot))
    if should_refresh:
        try:
            quote = _fetch_yahoo_quote(symbol)
            return _snapshot_to_quote(_save_quote_snapshot(ticker, symbol, quote)), 'live', None
        except (HTTPError, URLError, TimeoutError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            if snapshot:
                return _snapshot_to_quote(snapshot), 'saved', str(exc)
            raise
    if snapshot:
        return _snapshot_to_quote(snapshot), 'saved', None
    raise ValueError('No saved quote for %s' % symbol)


def _fx_rate_to_chf(currency):
    currency = (currency or 'CHF').upper()
    if currency == 'CHF':
        return Decimal('1')
    if currency == 'USD':
        symbol = 'USDCHF=X'
    elif currency == 'EUR':
        symbol = 'EURCHF=X'
    else:
        symbol = '%sCHF=X' % currency
    return _fetch_yahoo_quote(symbol)['price']


def _fx_rate_to_chf_saved(currency, force_refresh=False, auto_refresh=True):
    currency = (currency or 'CHF').upper()
    if currency == 'CHF':
        return Decimal('1'), 'fixed', None
    symbol = 'USDCHF=X' if currency == 'USD' else 'EURCHF=X' if currency == 'EUR' else '%sCHF=X' % currency
    quote, status, error = _quote_for_symbol('%sCHF' % currency, symbol, force_refresh=force_refresh, auto_refresh=auto_refresh)
    return quote['price'], status, error


def _snapshot_fx_rate_to_chf(currency):
    return STOCK_SNAPSHOT_FX_TO_CHF.get((currency or 'CHF').upper(), Decimal('1'))


def normalize_ticker(value):
    return (value or '').strip().upper()


def parse_decimal(value, default=None):
    if value in (None, ''):
        return default
    return Decimal(str(value).strip())


def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, '%Y-%m-%d').date()


def parse_datetime_local(value):
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, '%Y-%m-%dT%H:%M')
    except ValueError:
        parsed_date = parse_date(value)
        parsed = datetime.combine(parsed_date, datetime.min.time())
    if settings.USE_TZ and django_timezone.is_naive(parsed):
        return django_timezone.make_aware(parsed, django_timezone.get_current_timezone())
    return parsed


def configured_stock_holdings():
    holdings = []
    for holding in STOCK_HOLDINGS:
        copied = dict(holding)
        target = STOCK_TARGETS.get(copied['ticker'], {})
        copied.update({
            'source': 'static',
            'bought_at': '',
            'category': STOCK_NOTES.get(copied['ticker'], {}).get('category', ''),
            'why_own': STOCK_NOTES.get(copied['ticker'], {}).get('why', ''),
            'target_price': target.get('target_price'),
            'target_currency': target.get('target_currency', copied['cost_currency']),
            'target_date': target.get('target_date', ''),
            'target_note': target.get('target_note', ''),
            'target_quantity': target.get('target_quantity'),
            'reference_price': target.get('reference_price'),
            'reference_date': target.get('reference_date', ''),
        })
        holdings.append(copied)

    for holding in StockHolding.objects.filter(active=True):
        fallback_value = holding.fallback_value
        if fallback_value is None:
            fallback_value = holding.shares * holding.average_price
        holdings.append({
            'source': 'local',
            'id': holding.id,
            'name': holding.name,
            'ticker': normalize_ticker(holding.ticker),
            'symbol': holding.symbol.strip(),
            'shares': holding.shares,
            'average_price': holding.average_price,
            'cost_currency': holding.cost_currency,
            'fallback_value': fallback_value,
            'fallback_currency': holding.fallback_currency,
            'bought_at': holding.bought_at.isoformat(),
            'category': holding.category,
            'why_own': holding.why_own,
            'target_price': holding.target_price,
            'target_currency': holding.target_currency,
            'target_date': holding.target_date.isoformat() if holding.target_date else '',
            'target_note': holding.target_note,
            'target_quantity': holding.shares,
            'reference_price': holding.average_price,
            'reference_date': holding.bought_at.isoformat(),
        })
    return holdings


def stock_detail_url(ticker):
    return '/dashboard/stocks/holding/%s/' % normalize_ticker(ticker).lower()


def find_stock_holding(ticker):
    normalized = normalize_ticker(ticker)
    for holding in configured_stock_holdings():
        if holding['ticker'] == normalized:
            return holding
    raise Http404('Stock holding not found')


def serialize_stock_holding(holding, price, currency, value, value_chf, cost_value, cost_chf, unrealized_chf, quote_status, error, updated_at=None):
    target_price = holding.get('target_price')
    target_currency = holding.get('target_currency') or currency
    target_quantity = holding.get('target_quantity') or holding['shares']
    target_value = target_price * target_quantity if target_price else None
    return {
        'name': holding['name'],
        'ticker': holding['ticker'],
        'symbol': holding['symbol'],
        'shares': float(holding['shares']),
        'price': float(price),
        'currency': currency,
        'value': float(value),
        'value_chf': float(value_chf),
        'average_price': float(holding['average_price']),
        'cost_currency': holding['cost_currency'],
        'cost_value': float(cost_value),
        'cost_chf': float(cost_chf),
        'unrealized_chf': float(unrealized_chf),
        'live': quote_status == 'live',
        'quote_status': quote_status,
        'error': error,
        'quote_updated_at': updated_at.isoformat() if updated_at else None,
        'category': holding.get('category', ''),
        'why_own': holding.get('why_own', ''),
        'bought_at': holding.get('bought_at', ''),
        'detail_url': stock_detail_url(holding['ticker']),
        'target_price': float(target_price) if target_price else None,
        'target_currency': target_currency,
        'target_value': float(target_value) if target_value else None,
        'target_date': holding.get('target_date', ''),
        'target_note': holding.get('target_note', ''),
        'target_quantity': float(target_quantity) if target_quantity else None,
        'reference_price': float(holding['reference_price']) if holding.get('reference_price') else None,
        'reference_date': holding.get('reference_date', ''),
        'source': holding.get('source', ''),
    }


@require_dashboard_auth
def stock_portfolio(request):
    force_refresh = request.GET.get('live') == '1' or request.GET.get('refresh') == '1'
    auto_refresh = request.GET.get('auto') != '0'
    fx_cache = {}
    holdings = []
    totals = {
        'USD': Decimal('0'),
        'EUR': Decimal('0'),
        'CHF': Decimal('0'),
        'cost_chf': Decimal('0'),
    }
    live_count = 0
    saved_count = 0
    fallback_count = 0
    quote_updated_times = []

    stock_configs = configured_stock_holdings()
    for holding in stock_configs:
        error = None
        quote_updated_at = None
        try:
            quote, quote_status, quote_error = _quote_for_symbol(
                holding['ticker'],
                holding['symbol'],
                force_refresh=force_refresh,
                auto_refresh=auto_refresh,
            )
            price = quote['price']
            currency = quote['currency']
            value = price * holding['shares']
            error = quote_error
            saved_snapshot = _saved_quote(holding['ticker'], holding['symbol'])
            quote_updated_at = saved_snapshot.updated_at if saved_snapshot else None
            if quote_updated_at:
                quote_updated_times.append(quote_updated_at)
            if quote_status == 'live':
                live_count += 1
            elif quote_status == 'saved':
                saved_count += 1
        except (HTTPError, URLError, TimeoutError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            price = holding['fallback_value'] / holding['shares'] if holding['shares'] else Decimal('0')
            currency = holding['fallback_currency']
            value = holding['fallback_value']
            quote_status = 'fallback'
            fallback_count += 1
            error = str(exc) if force_refresh or auto_refresh else 'Stored IBKR snapshot'

        fx_key = currency
        if fx_key not in fx_cache:
            try:
                fx_cache[fx_key], _fx_status, _fx_error = _fx_rate_to_chf_saved(
                    fx_key,
                    force_refresh=force_refresh,
                    auto_refresh=auto_refresh,
                )
            except (HTTPError, URLError, TimeoutError, KeyError, IndexError, ValueError, json.JSONDecodeError):
                fx_cache[fx_key] = Decimal('0.89') if fx_key == 'EUR' else Decimal('0.80') if fx_key == 'USD' else Decimal('1')

        cost_currency = holding['cost_currency']
        if cost_currency not in fx_cache:
            try:
                fx_cache[cost_currency], _fx_status, _fx_error = _fx_rate_to_chf_saved(
                    cost_currency,
                    force_refresh=force_refresh,
                    auto_refresh=auto_refresh,
                )
            except (HTTPError, URLError, TimeoutError, KeyError, IndexError, ValueError, json.JSONDecodeError):
                fx_cache[cost_currency] = Decimal('0.89') if cost_currency == 'EUR' else Decimal('0.80') if cost_currency == 'USD' else Decimal('1')

        value_chf = value * fx_cache[fx_key]
        cost_value = holding['shares'] * holding['average_price']
        cost_chf = cost_value * fx_cache[cost_currency]
        unrealized_chf = value_chf - cost_chf
        totals['CHF'] += value_chf
        totals['cost_chf'] += cost_chf
        if currency in totals:
            totals[currency] += value

        holdings.append(serialize_stock_holding(
            holding, price, currency, value, value_chf, cost_value, cost_chf, unrealized_chf, quote_status, error, quote_updated_at
        ))

    if not holdings:
        response_total_chf = STOCK_SNAPSHOT['ibkr_nav_eur'] * STOCK_SNAPSHOT['eur_chf']
        response_total_cost_chf = STOCK_SNAPSHOT['table_cost_eur'] * STOCK_SNAPSHOT['eur_chf']
        response_unrealized_chf = STOCK_SNAPSHOT['table_unrealized_eur'] * STOCK_SNAPSHOT['eur_chf']
    else:
        response_total_chf = totals['CHF']
        response_total_cost_chf = totals['cost_chf']
        response_unrealized_chf = totals['CHF'] - totals['cost_chf']

    chf_to_eur = Decimal('1') / fx_cache.get('EUR', _snapshot_fx_rate_to_chf('EUR'))
    chf_to_usd = Decimal('1') / fx_cache.get('USD', _snapshot_fx_rate_to_chf('USD'))
    latest_quote_updated_at = max(quote_updated_times) if quote_updated_times else None
    if live_count:
        pricing_mode = 'live'
    elif saved_count:
        pricing_mode = 'saved'
    else:
        pricing_mode = 'fallback'
    if live_count:
        current_snapshot = get_current_portfolio_snapshot()
        current_snapshot.stocks_chf = response_total_chf.quantize(Decimal('0.01'))
        current_snapshot.save(update_fields=['stocks_chf', 'updated_at'])
    return JsonResponse({
        'status': 'ok',
        'source': 'Yahoo Finance' if live_count or saved_count else STOCK_SNAPSHOT['label'],
        'pricing_mode': pricing_mode,
        'live_count': live_count,
        'saved_count': saved_count,
        'fallback_count': fallback_count,
        'total_count': len(stock_configs),
        'latest_quote_updated_at': latest_quote_updated_at.isoformat() if latest_quote_updated_at else None,
        'total_chf': float(response_total_chf),
        'total_cost_chf': float(response_total_cost_chf),
        'unrealized_chf': float(response_unrealized_chf),
        'fx_from_chf': {
            'CHF': 1,
            'EUR': float(chf_to_eur),
            'USD': float(chf_to_usd),
            'GBP': 0.89,
        },
        'snapshot': {
            'label': STOCK_SNAPSHOT['label'],
            'ibkr_nav_eur': float(STOCK_SNAPSHOT['ibkr_nav_eur']),
            'table_value_eur': float(STOCK_SNAPSHOT['table_value_eur']),
            'table_cost_eur': float(STOCK_SNAPSHOT['table_cost_eur']),
            'table_unrealized_eur': float(STOCK_SNAPSHOT['table_unrealized_eur']),
            'excludes_extra_mstr_shares': 13.4785,
        },
        'totals': {
            'USD': float(totals['USD']),
            'EUR': float(totals['EUR']),
            'CHF': float(totals['CHF']),
        },
        'holdings': holdings,
    })


@require_dashboard_auth
def treasury_stock_data(request, slug):
    config = TREASURY_STOCKS.get(slug)
    if not config:
        return JsonResponse({
            'status': 'not_found',
            'error': 'Unknown treasury stock',
            'points': [],
        }, status=404)

    start = request.GET.get('start', config.get('start', '2024-01-01'))
    try:
        stock_months = _month_end_points(_fetch_yahoo_daily_series(config['symbol'], start))
        benchmark_months = _month_end_points(_fetch_yahoo_daily_series(config['benchmark_symbol'], start))
        points = []
        for month in sorted(set(stock_months) & set(benchmark_months)):
            stock_point = stock_months[month]
            benchmark_point = benchmark_months[month]
            benchmark_per_share = stock_point['close'] / benchmark_point['close']
            points.append({
                'date': stock_point['date'].strftime('%Y-%m-%d'),
                'label': stock_point['date'].strftime('%b %Y'),
                'stock_price': round(stock_point['close'], 4),
                'benchmark_price': round(benchmark_point['close'], 2),
                'benchmark_per_share': round(benchmark_per_share, 10),
                'units_per_share': round(benchmark_per_share * SATOSHIS_PER_BTC),
            })
        return JsonResponse({
            'status': 'ok',
            'source': 'Yahoo Finance',
            'stock': config,
            'symbol': '%s/%s' % (config['symbol'], config['benchmark_symbol']),
            'formula': '%s adjusted close / %s close * 100,000,000' % (config['symbol'], config['benchmark_symbol']),
            'points': points,
        })
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({
            'status': 'unavailable',
            'source': 'Yahoo Finance',
            'error': 'Could not build treasury stock chart data',
            'detail': str(exc),
            'points': [],
        }, status=503)


@require_dashboard_auth
def mstr_btc(request):
    start = request.GET.get('start', '2021-06-01')
    try:
        mstr_months = _month_end_points(_fetch_yahoo_daily_series('MSTR', start))
        btc_months = _month_end_points(_fetch_yahoo_daily_series('BTC-USD', start))
        points = []
        for month in sorted(set(mstr_months) & set(btc_months)):
            mstr_point = mstr_months[month]
            btc_point = btc_months[month]
            btc_per_share = mstr_point['close'] / btc_point['close']
            points.append({
                'date': mstr_point['date'].strftime('%Y-%m-%d'),
                'label': mstr_point['date'].strftime('%b %Y'),
                'mstr_usd': round(mstr_point['close'], 2),
                'btc_usd': round(btc_point['close'], 2),
                'btc_per_share': round(btc_per_share, 8),
                'sats_per_share': round(btc_per_share * SATOSHIS_PER_BTC),
            })
        return JsonResponse({
            'status': 'ok',
            'source': 'Yahoo Finance',
            'symbol': 'MSTR/BTC',
            'formula': 'MSTR adjusted close / BTC-USD close * 100,000,000',
            'points': points,
        })
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({
            'status': 'unavailable',
            'source': 'Yahoo Finance',
            'error': 'Could not build MSTR/BTC chart data',
            'detail': str(exc),
            'points': [],
        }, status=503)


@require_dashboard_auth
def ibkr_portfolio(request):
    base_url = os.environ.get('IBKR_GATEWAY_URL', 'https://localhost:5000').rstrip('/')
    context = ssl._create_unverified_context()

    def get_json(path):
        url = '%s%s' % (base_url, path)
        req = urlrequest.Request(url, headers={'Accept': 'application/json'})
        with urlrequest.urlopen(req, timeout=6, context=context) as response:
            return json.loads(response.read().decode('utf-8'))

    try:
        auth_status = get_json('/v1/api/iserver/auth/status')
        accounts = get_json('/v1/api/portfolio/accounts')
        if not accounts:
            raise ValueError('No IBKR accounts returned')

        account_id = accounts[0].get('id') or accounts[0].get('accountId') or accounts[0].get('account')
        if not account_id:
            raise ValueError('No IBKR account identifier returned')

        summary = get_json('/v1/api/portfolio/%s/summary' % parse.quote(str(account_id)))
        net_liquidation = None
        currency = None
        for key, value in summary.items():
            normalized_key = key.lower().replace(' ', '').replace('_', '')
            if normalized_key in ('netliquidation', 'netliquidationvalue', 'totalcashvalue'):
                if isinstance(value, dict):
                    net_liquidation = value.get('amount') or value.get('value')
                    currency = value.get('currency') or currency
                else:
                    net_liquidation = value
                break

        return JsonResponse({
            'status': 'connected',
            'gateway_url': base_url,
            'auth': auth_status,
            'account': accounts[0],
            'account_id': account_id,
            'summary': summary,
            'net_liquidation': net_liquidation,
            'currency': currency,
        })
    except (HTTPError, URLError, TimeoutError, ssl.SSLError, ValueError, json.JSONDecodeError) as error:
        return JsonResponse({
            'status': 'unavailable',
            'gateway_url': base_url,
            'message': 'IBKR Client Portal Gateway is not reachable or not authenticated.',
            'detail': str(error),
        }, status=503)


@login_required
def add_comment(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if request.method == 'POST':
        user = User.objects.get(id=request.POST.get('user_id'))
        text = request.POST.get('text')
        Comment(author=user, post=post, text=text).save()
        messages.success(request, "Your comment has been added successfully.")
    else:
        return redirect('post_detail', pk=pk)
    return redirect('post_detail', pk=pk)
