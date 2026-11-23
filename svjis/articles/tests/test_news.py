from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from ..models import News


class NewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.editor = User.objects.create_user(username='news-editor')
        cls.editor.user_permissions.add(
            Permission.objects.get(content_type__app_label='articles', codename='svjis_edit_article_news')
        )
        cls.reader = User.objects.create_user(username='news-reader')
        cls.admin = User.objects.create_superuser(username='news-admin')

    def create_news(self, body='News announcement', **fields):
        return News.objects.create(author=self.editor, body=body, **fields)

    def save_news(self, **data):
        return self.client.post(reverse('redaction_news_save'), {'pk': 0, **data})

    @override_settings(SVJIS_NEWS_PAGE_SIZE=10)
    def test_publication_bounds_and_redaction_statuses(self):
        now = datetime(2027, 6, 16, 8, tzinfo=UTC)
        before = now - timedelta(minutes=1)
        after = now + timedelta(minutes=1)
        cases = [
            (self.create_news('Undated announcement', published=True), 'active'),
            (self.create_news('Starts now', published=True, publish_at=now), 'active'),
            (self.create_news('Will start later', published=True, publish_at=after), 'scheduled'),
            (self.create_news('Ends later', published=True, expires_at=after), 'active'),
            (self.create_news('Ends now', published=True, expires_at=now), 'expired'),
            (self.create_news('Inside both bounds', published=True, publish_at=before, expires_at=after), 'active'),
            (self.create_news('Was active', published=True, publish_at=before, expires_at=now), 'expired'),
            (self.create_news('Unpublished in future', publish_at=after), 'draft'),
            (self.create_news('Unpublished in past', expires_at=before), 'draft'),
        ]
        expected_statuses = {news.pk: status for news, status in cases}
        active_ids = {pk for pk, status in expected_statuses.items() if status == 'active'}
        self.assertEqual(set(News.objects.active(at=now).values_list('pk', flat=True)), active_ids)
        self.assertEqual(
            dict(News.objects.with_publication_status(at=now).values_list('pk', 'publication_status')),
            expected_statuses,
        )

        with patch('articles.managers.timezone.now', return_value=now):
            response = self.client.get(reverse('main'))
            for news, status in cases:
                with self.subTest(body=news.body, status=status):
                    if status == 'active':
                        self.assertContains(response, news.body)
                    else:
                        self.assertNotContains(response, news.body)

            self.client.force_login(self.editor)
            response = self.client.get(reverse('redaction_news'), HTTP_ACCEPT_LANGUAGE='en')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                {row.pk: row.publication_status for row in response.context['object_list']}, expected_statuses
            )
            for status in set(expected_statuses.values()):
                self.assertContains(response, status.capitalize())

    def test_announcement_appears_and_disappears_without_deletion(self):
        starts = datetime(2027, 6, 16, 8, tzinfo=UTC)
        ends = starts + timedelta(hours=1)
        news = self.create_news('Limited announcement', published=True, publish_at=starts, expires_at=ends)
        for instant, visible in ((starts - timedelta(seconds=1), False), (starts, True), (ends, False)):
            with self.subTest(instant=instant), patch('articles.managers.timezone.now', return_value=instant):
                response = self.client.get(reverse('main'))
                if visible:
                    self.assertContains(response, news.body)
                else:
                    self.assertNotContains(response, news.body)
        news.refresh_from_db()
        self.assertTrue(news.published)
        self.assertEqual(news.expires_at, ends)

    def test_editor_can_republish_an_expired_announcement(self):
        now = datetime(2027, 6, 16, 8, tzinfo=UTC)
        news = self.create_news('Republishable news', published=True, expires_at=now - timedelta(days=1))
        with patch('articles.managers.timezone.now', return_value=now):
            self.assertNotContains(self.client.get(reverse('main')), news.body)
            self.client.force_login(self.editor)
            edit = self.client.get(reverse('redaction_news_edit', kwargs={'pk': news.pk}))
            self.assertContains(edit, news.body)
            response = self.save_news(pk=news.pk, body=news.body, published='on', expires_at='')
            self.assertRedirects(response, reverse('redaction_news'))
            self.client.logout()
            self.assertContains(self.client.get(reverse('main')), news.body)
        news.refresh_from_db()
        self.assertIsNone(news.expires_at)

    @override_settings(USE_TZ=True, TIME_ZONE='Europe/Prague')
    def test_event_only_news_with_local_publication_dates(self):
        self.client.force_login(self.editor)
        link = 'https://example.org/meeting?entrance=a&floor=2'
        with timezone.override('Europe/Prague'):
            response = self.save_news(
                event_title='Residents meeting',
                event_date='2027-06-16',
                event_start_time='18:15',
                event_end_time='19:45',
                event_location='Main hall',
                event_link=link,
                published='on',
                publish_at='2027-06-15T09:00',
                expires_at='2027-06-17T09:00',
            )
            self.assertEqual(response.status_code, 302)
            news = News.objects.get()
            self.assertEqual(news.author, self.editor)
            self.assertEqual(news.body, '')
            self.assertFalse(news.body_is_legacy_html)
            self.assertEqual(news.event_title, 'Residents meeting')
            self.assertEqual(news.event_location, 'Main hall')
            self.assertEqual(news.event_link, link)
            self.assertEqual(news.event_date, date(2027, 6, 16))
            self.assertEqual(news.event_start_time, time(18, 15))
            self.assertEqual(news.event_end_time, time(19, 45))
            self.assertEqual(news.publish_at, datetime(2027, 6, 15, 7, tzinfo=UTC))
            self.assertEqual(news.expires_at, datetime(2027, 6, 17, 7, tzinfo=UTC))
            edit = self.client.get(reverse('redaction_news_edit', kwargs={'pk': news.pk}))
            self.assertContains(edit, '2027-06-15T09:00')
            self.assertContains(edit, '2027-06-17T09:00')

            self.client.logout()
            with patch('articles.managers.timezone.now', return_value=news.publish_at):
                public = self.client.get(reverse('main'))
            for text in (
                'Residents meeting',
                'datetime="2027-06-16"',
                'Main hall',
                '18:15',
                '19:45',
                f'href="{escape(link)}"',
            ):
                self.assertContains(public, text)

    def test_body_or_one_event_field_is_required(self):
        self.client.force_login(self.editor)
        response = self.save_news(body='  ', publish_at='2027-06-15T09:00', published='on')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(News.objects.exists())

        for field, value in (
            ('body', 'Just an announcement'),
            ('event_title', 'Meeting'),
            ('event_date', '2027-06-16'),
            ('event_start_time', '18:15'),
            ('event_end_time', '19:45'),
            ('event_location', 'Main hall'),
            ('event_link', '/contact/'),
        ):
            with self.subTest(field=field):
                self.assertEqual(self.save_news(**{field: value}).status_code, 302)
        self.assertEqual(News.objects.count(), 7)

    def test_invalid_publication_window_shows_errors_without_overwriting_news(self):
        self.client.force_login(self.editor)
        news = self.create_news('Original announcement', published=True)
        for expiry in ('2027-06-15T09:00', '2027-06-15T08:00'):
            with self.subTest(expiry=expiry):
                response = self.save_news(
                    pk=news.pk,
                    body='Edited announcement',
                    event_title='Event from unsaved form',
                    publish_at='2027-06-15T09:00',
                    expires_at=expiry,
                )
                self.assertContains(response, 'Edited announcement')
                self.assertContains(response, 'Event from unsaved form')
                errors = response.context['form'].errors
                self.assertTrue(errors)
                for error_list in errors.values():
                    for error in error_list:
                        self.assertContains(response, escape(error))
                news.refresh_from_db()
                self.assertEqual(news.body, 'Original announcement')
                self.assertTrue(news.published)
                self.assertIsNone(news.publish_at)
                self.assertIsNone(news.expires_at)

    def test_database_rejects_equal_or_reversed_publication_bounds(self):
        starts = datetime(2027, 6, 16, 8, tzinfo=UTC)
        for ends in (starts, starts - timedelta(minutes=1)):
            with self.subTest(ends=ends), self.assertRaises(IntegrityError), transaction.atomic():
                self.create_news(publish_at=starts, expires_at=ends)

    def test_new_text_is_escaped_and_safe_event_links_are_rendered(self):
        self.client.force_login(self.editor)
        body = '<em>Plain body</em>'
        title = '<b>Plain title</b>'
        location = '<i>Plain location</i>'
        links = ('http://example.org/event', 'https://example.org/event', '/contact/?a=1&b=2')
        for link in links:
            with self.subTest(link=link):
                response = self.save_news(
                    body=body,
                    event_title=title,
                    event_location=location,
                    event_link=link,
                    published='on',
                    body_is_legacy_html='on',  # The legacy flag is not user-settable.
                )
                self.assertEqual(response.status_code, 302)
        self.assertFalse(News.objects.filter(body_is_legacy_html=True).exists())

        self.client.logout()
        response = self.client.get(reverse('main'))
        for value in (body, title, location):
            with self.subTest(value=value):
                self.assertContains(response, escape(value))
                self.assertNotContains(response, value)
        for link in links:
            self.assertContains(response, f'href="{escape(link)}"')

    def test_invalid_event_links_are_rejected(self):
        self.client.force_login(self.editor)
        for link in ('javascript:void(0)', 'data:text/plain,hello', 'ftp://example.org/event', '//example.org/event'):
            with self.subTest(link=link):
                response = self.save_news(body='Meeting', event_link=link, published='on')
                self.assertEqual(response.status_code, 200)
                self.assertIn('event_link', response.context['form'].errors)
        self.assertFalse(News.objects.exists())

    def test_unsafe_link_written_without_form_validation_is_not_rendered(self):
        self.create_news('Announcement with invalid link', published=True, event_link='javascript:void(0)')
        response = self.client.get(reverse('main'))
        self.assertContains(response, 'Announcement with invalid link')
        self.assertNotContains(response, 'href="javascript:void(0)"')

    def test_unchanged_legacy_body_keeps_markup_but_edited_body_becomes_plain_text(self):
        original = '  <em>Legacy formatted body</em>\nNext legacy line  '
        news = self.create_news(original, published=True, body_is_legacy_html=True)
        self.assertContains(self.client.get(reverse('main')), '<em>Legacy formatted body</em>')

        self.client.force_login(self.editor)
        response = self.save_news(
            pk=news.pk, body=original.replace('\n', '\r\n'), event_title='Added later', published='on'
        )
        self.assertEqual(response.status_code, 302)
        news.refresh_from_db()
        self.assertEqual(news.event_title, 'Added later')
        self.assertEqual(news.body, original)
        self.assertTrue(news.body_is_legacy_html)
        self.assertContains(self.client.get(reverse('main')), original)

        edited = '<em>Edited legacy body</em>'
        response = self.save_news(pk=news.pk, body=edited, event_title='Added later', published='on')
        self.assertEqual(response.status_code, 302)
        news.refresh_from_db()
        self.assertEqual(news.body, edited)
        self.assertFalse(news.body_is_legacy_html)
        response = self.client.get(reverse('main'))
        self.assertContains(response, escape(edited))
        self.assertNotContains(response, edited)

    def test_django_admin_adds_event_only_news_and_shows_schedule_status(self):
        now = datetime(2027, 6, 15, 12, tzinfo=UTC)
        with patch('articles.managers.timezone.now', return_value=now):
            self.client.force_login(self.admin)
            response = self.client.post(
                reverse('admin:articles_news_add'),
                {
                    'author': self.editor.pk,
                    'event_title': 'Future event from Django admin',
                    'publish_at': '2027-06-17T12:00',
                    'published': 'on',
                    '_save': 'Save',
                },
            )
            self.assertEqual(response.status_code, 302)
            news = News.objects.get()
            self.assertEqual(news.author, self.editor)
            self.assertEqual(news.body, '')
            self.assertFalse(news.body_is_legacy_html)
            listing = self.client.get(reverse('admin:articles_news_changelist'), HTTP_ACCEPT_LANGUAGE='en')
            self.assertContains(listing, 'Future event from Django admin')
            self.assertContains(listing, 'Scheduled')

    def test_django_admin_validates_content_and_retires_edited_legacy_markup(self):
        self.client.force_login(self.admin)
        news = self.create_news('<em>Legacy announcement</em>', published=True, body_is_legacy_html=True)
        change_url = reverse('admin:articles_news_change', args=[news.pk])
        data = {'author': self.editor.pk, 'published': 'on', '_save': 'Save'}

        response = self.client.post(change_url, {**data, 'body': '  '})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['adminform'].form.non_field_errors())
        news.refresh_from_db()
        self.assertEqual(news.body, '<em>Legacy announcement</em>')
        self.assertTrue(news.body_is_legacy_html)

        edited = '<em>Changed from Django admin</em>'
        response = self.client.post(change_url, {**data, 'body': edited})
        self.assertEqual(response.status_code, 302)
        news.refresh_from_db()
        self.assertEqual(news.body, edited)
        self.assertFalse(news.body_is_legacy_html)

    def test_direct_redaction_access_requires_news_permission(self):
        news = self.create_news('Private announcement')
        get_urls = [
            reverse('redaction_news'),
            reverse('redaction_news_edit', kwargs={'pk': 0}),
            reverse('redaction_news_edit', kwargs={'pk': news.pk}),
            reverse('redaction_news_delete', kwargs={'pk': news.pk}),
        ]
        for user in (None, self.reader):
            if user:
                self.client.force_login(user)
            with self.subTest(user=user):
                for url in get_urls:
                    self.assertEqual(self.client.get(url).status_code, 302)
                self.assertEqual(self.save_news(body='Unauthorized creation', published='on').status_code, 302)
                self.assertEqual(
                    self.save_news(pk=news.pk, body='Unauthorized change', published='on').status_code, 302
                )
        self.assertEqual(News.objects.count(), 1)
        news.refresh_from_db()
        self.assertEqual(news.body, 'Private announcement')
        self.assertFalse(news.published)
