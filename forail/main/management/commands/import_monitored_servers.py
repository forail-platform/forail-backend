"""import_monitored_servers -- bring servers registered in Forail Mobile under platform RBAC.

Before forail-mobile#52, monitored servers were registered in the Forail Mobile
backend by superusers, and who could see them was a member list kept there.
Now the platform decides. This command creates a ``MonitoredServer`` for every
server the mobile backend has that the platform does not know yet, puts it in
an organization, makes ``--owner`` its owner, and -- with ``--grant-members`` --
gives each user on the old member list ``read_role``.

Idempotent: servers already linked are skipped. Nothing changes with --dry-run.

    forail-manage import_monitored_servers --organization Default --owner admin --grant-members --dry-run
    forail-manage import_monitored_servers --organization Shop --owner ana --only web-01,web-02
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from forail.main.models import Organization
from forail.main.models.monitored_server import SERVER_NAME, MonitoredServer
from forail.main.services import forail_mobile


class Command(BaseCommand):
    help = 'Create platform records for monitored servers that exist only in Forail Mobile.'

    def add_arguments(self, parser):
        parser.add_argument('--organization', required=True, help='Organization the imported servers belong to (name or id).')
        parser.add_argument('--owner', required=True, help='Username of the user who will own them.')
        parser.add_argument('--grant-members', action='store_true', help='Give read access to the users on each server\'s old member list.')
        parser.add_argument('--only', default='', help='Comma-separated server names to import; default all unknown ones.')
        parser.add_argument('--dry-run', action='store_true', help='Report what would happen and change nothing.')

    def handle(self, *args, **options):
        if not forail_mobile.enabled():
            raise CommandError('Set FORAIL_MOBILE_URL and FORAIL_MOBILE_SERVICE_TOKEN first.')
        org = self._organization(options['organization'])
        owner = User.objects.filter(username=options['owner']).first()
        if owner is None:
            raise CommandError(f'No user named {options["owner"]}.')

        client = forail_mobile.ForailMobileClient()
        try:
            remote = client.servers()
        except forail_mobile.MobileUnavailable as e:
            raise CommandError(str(e))

        known = {str(u) for u in MonitoredServer.objects.values_list('mobile_server_id', flat=True)}
        taken = set(MonitoredServer.objects.filter(organization=org).values_list('name', flat=True))
        only = {n.strip() for n in options['only'].split(',') if n.strip()}
        created = skipped = granted = 0
        for row in sorted(remote, key=lambda r: r['name']):
            if only and row['name'] not in only:
                continue
            if row['id'] in known:
                skipped += 1
                continue
            if not SERVER_NAME.match(row['name']) or row['name'] in taken:
                self.stderr.write(f'  skip {row["name"]}: the name is invalid or already used in {org.name}')
                skipped += 1
                continue
            members = list(User.objects.filter(pk__in=[int(s) for s in row.get('legacy_members', []) if str(s).isdigit()])) if options['grant_members'] else []
            self.stdout.write(f'  {row["name"]} ({row["id"]}) -> {org.name}, owner {owner.username}' + (f', read: {", ".join(u.username for u in members)}' if members else ''))
            if options['dry_run']:
                created += 1
                granted += len(members)
                continue
            with transaction.atomic():
                server = MonitoredServer.objects.create(name=row['name'], organization=org, owner=owner, mobile_server_id=row['id'])
                server.admin_role.members.add(owner)
                for member in members:
                    server.read_role.members.add(member)
                client.link(row['id'], org.pk, owner.pk)
            taken.add(row['name'])
            created += 1
            granted += len(members)

        verb = 'Would import' if options['dry_run'] else 'Imported'
        self.stdout.write(self.style.SUCCESS(f'{verb} {created} server(s), {granted} read grant(s); {skipped} skipped.'))

    def _organization(self, value):
        qs = Organization.objects.filter(pk=int(value)) if value.isdigit() else Organization.objects.filter(name=value)
        org = qs.first()
        if org is None:
            raise CommandError(f'No organization {value}.')
        return org
