from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase


class PendingMigrationsTests(TestCase):
    def test_no_pending_migrations(self):
        out = StringIO()
        try:
            call_command(
                "makemigrations",
                "--check",
                stdout=out,
                stderr=StringIO(),
            )
        except SystemExit:  # pragma: no cover
            raise AssertionError("Pending migrations:\n" + out.getvalue()) from None


class NewsMigrationTests(TransactionTestCase):
    def test_existing_news_keeps_content_and_publication_state(self):
        old_migration = ('articles', '0013_articlelog_referer')
        new_migration = ('articles', '0014_news_events_and_publication')
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()

        try:
            executor.migrate([old_migration])
            old_models = executor.loader.project_state([old_migration]).apps
            old_news = old_models.get_model('articles', 'News')
            author_id = get_user_model().objects.create_user(username='legacy-news-editor').pk
            legacy = [
                old_news.objects.create(author_id=author_id, body='<em>Legacy news</em>', published=True),
                old_news.objects.create(author_id=author_id, body='Old draft', published=False),
            ]

            executor = MigrationExecutor(connection)
            executor.migrate([new_migration])
            new_models = executor.loader.project_state([new_migration]).apps
            news = new_models.get_model('articles', 'News')
            for old in legacy:
                with self.subTest(published=old.published):
                    migrated = news.objects.get(pk=old.pk)
                    self.assertEqual(migrated.author_id, old.author_id)
                    self.assertEqual(migrated.created_date, old.created_date)
                    self.assertEqual(migrated.body, old.body)
                    self.assertEqual(migrated.published, old.published)
                    self.assertTrue(migrated.body_is_legacy_html)
                    self.assertIsNone(migrated.publish_at)
                    self.assertIsNone(migrated.expires_at)
                    for field in (
                        'event_title',
                        'event_date',
                        'event_start_time',
                        'event_end_time',
                        'event_location',
                        'event_link',
                    ):
                        self.assertIsNone(getattr(migrated, field))

            self.assertFalse(news.objects.create(author_id=author_id, body='New news').body_is_legacy_html)
        finally:
            MigrationExecutor(connection).migrate(latest)
