from django.urls import path

from forail.api.views.recommendations import RecommendationsList


urlpatterns = [
    path('', RecommendationsList.as_view(), name='recommendations_list'),
]
