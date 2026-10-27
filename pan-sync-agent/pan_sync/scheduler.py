from datetime import timedelta


def in_window(now, start_hour, end_hour):
    return start_hour <= now.hour < end_hour


def seconds_until_start(now, start_hour):
    target = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def next_interval_delay(now, interval_minutes, start_hour, end_hour):
    target = now + timedelta(minutes=interval_minutes)
    if not in_window(target, start_hour, end_hour):
        return seconds_until_start(now, start_hour)
    return (target - now).total_seconds()
