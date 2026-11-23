from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from . import forms, models


@admin.register(models.News)
class NewsAdmin(admin.ModelAdmin):
    form = forms.NewsForm
    fieldsets = (
        (_("News content"), {'fields': ('author', 'body')}),
        (_("Event information (optional)"), {'fields': forms.NEWS_EVENT_FIELDS}),
        (_("Publication settings"), {'fields': forms.NEWS_PUBLICATION_FIELDS}),
    )
    list_display = ('__str__', 'author', 'created_date', 'display_publication_status')

    def get_queryset(self, request):
        return super().get_queryset(request).with_publication_status()

    @admin.display(description=_("Status"))
    def display_publication_status(self, obj):
        return obj.publication_status_label


# Register your models here.

admin.site.register(models.Article)
admin.site.register(models.ArticleLog)
admin.site.register(models.ArticleAsset)
admin.site.register(models.ArticleComment)
admin.site.register(models.ArticleMenu)
admin.site.register(models.UsefulLink)
admin.site.register(models.Survey)
admin.site.register(models.SurveyOption)
admin.site.register(models.SurveyAnswerLog)
admin.site.register(models.UserProfile)
admin.site.register(models.MessageQueue)
admin.site.register(models.Preferences)
admin.site.register(models.Company)
admin.site.register(models.Building)
admin.site.register(models.Board)
admin.site.register(models.BuildingEntrance)
admin.site.register(models.BuildingUnitType)
admin.site.register(models.BuildingUnit)
admin.site.register(models.FaultReport)
admin.site.register(models.FaultAsset)
admin.site.register(models.FaultComment)
admin.site.register(models.FaultReportLog)
admin.site.register(models.AdvertType)
admin.site.register(models.Advert)
admin.site.register(models.AdvertAsset)
