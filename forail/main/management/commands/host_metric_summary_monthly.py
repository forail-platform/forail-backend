from django.core.management.base import BaseCommand
from forail.main.tasks.host_metrics import HostMetricSummaryMonthlyTask


class Command(BaseCommand):
    help = 'Computing of HostMetricSummaryMonthly'

    def handle(self, *args, **options):
        HostMetricSummaryMonthlyTask().execute()
