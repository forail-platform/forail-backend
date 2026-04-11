from django.urls import path

from forge.api.views.recommendations import RecommendationsList


urlpatterns = [
    path('', RecommendationsList.as_view(), name='recommendations_list'),
]
