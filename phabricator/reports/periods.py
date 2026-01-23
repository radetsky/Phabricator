from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

PeriodType = Literal["monthly", "weekly"]


@dataclass
class Period:
    start: datetime
    end: datetime
    label: str  # "2024-01" for monthly or "2024-W03" for weekly


def generate_periods(
    start_date: datetime, end_date: datetime, period_type: PeriodType
) -> list[Period]:
    """
    Generate calendar-aligned periods between start_date and end_date.

    Monthly: align to calendar months (1st-last day), partial periods at start/end OK
    Weekly: align to ISO weeks (Mon-Sun), use label format YYYY-Wnn
    """
    periods = []

    if period_type == "monthly":
        current = datetime(start_date.year, start_date.month, 1)
        while current <= end_date:
            # Period start is max of month start and requested start_date
            period_start = max(current, start_date)

            # Calculate last day of month
            if current.month == 12:
                next_month = datetime(current.year + 1, 1, 1)
            else:
                next_month = datetime(current.year, current.month + 1, 1)
            month_end = next_month - timedelta(days=1)
            month_end = month_end.replace(hour=23, minute=59, second=59)

            # Period end is min of month end and requested end_date
            period_end = min(month_end, end_date.replace(hour=23, minute=59, second=59))

            label = current.strftime("%Y-%m")
            periods.append(Period(start=period_start, end=period_end, label=label))

            current = next_month

    elif period_type == "weekly":
        # Find Monday of the week containing start_date (ISO week starts Monday)
        days_since_monday = start_date.weekday()
        week_start = start_date - timedelta(days=days_since_monday)
        week_start = datetime(week_start.year, week_start.month, week_start.day)

        while week_start <= end_date:
            # Period start is max of week start and requested start_date
            period_start = max(week_start, start_date)

            # Week end is Sunday (6 days after Monday)
            week_end = week_start + timedelta(days=6)
            week_end = week_end.replace(hour=23, minute=59, second=59)

            # Period end is min of week end and requested end_date
            period_end = min(week_end, end_date.replace(hour=23, minute=59, second=59))

            # ISO week label format: YYYY-Wnn
            iso_year, iso_week, _ = period_start.isocalendar()
            label = f"{iso_year}-W{iso_week:02d}"

            periods.append(Period(start=period_start, end=period_end, label=label))

            week_start = week_start + timedelta(days=7)

    return periods
