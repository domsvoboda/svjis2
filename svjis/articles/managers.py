import typing

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

if typing.TYPE_CHECKING:
    from articles.models import FaultReportLog  # noqa: F401


class NewsPublicationStatus(models.TextChoices):
    DRAFT = 'draft', _("Draft")
    SCHEDULED = 'scheduled', _("Scheduled")
    ACTIVE = 'active', _("Active")
    EXPIRED = 'expired', _("Expired")


class NewsQuerySet(models.QuerySet):
    def with_publication_status(self, at=None):
        at = timezone.now() if at is None else at
        status = NewsPublicationStatus
        return self.annotate(
            publication_status=models.Case(
                models.When(published=False, then=models.Value(status.DRAFT)),
                models.When(publish_at__gt=at, then=models.Value(status.SCHEDULED)),
                models.When(expires_at__lte=at, then=models.Value(status.EXPIRED)),
                default=models.Value(status.ACTIVE),
            )
        )

    def active(self, at=None):
        return self.with_publication_status(at).filter(publication_status=NewsPublicationStatus.ACTIVE)


class FaultReportLogManager(models.Manager["FaultReportLog"]):
    def log_actions(self, request, form, queryset, created=False) -> None:
        result = []
        others_recorded = False
        for obj in queryset:
            for change in form.changed_data:
                if change == 'assigned_to_user' and not created:
                    _type = self.model.TYPE_ASSIGNED
                elif change == 'closed':
                    if form.cleaned_data['closed']:
                        _type = self.model.TYPE_CLOSED
                    else:
                        _type = self.model.TYPE_REOPENED
                else:
                    if others_recorded:
                        continue
                    _type = self.model.TYPE_MODIFIED if not created else self.model.TYPE_CREATED
                    others_recorded = True
                result.append(
                    self.model(
                        fault_report=obj,
                        user=request.user,
                        resolver=obj.assigned_to_user,
                        type=_type,
                    )
                )
        self.bulk_create(result)
