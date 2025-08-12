from django.urls import path
from .views import (
    GeneralCoursesView,
    MajorCoursesView,
    TotalCreditView,
    GeneralCreditView,
    MajorCreditView,
    StatisticsCreditView,
    StatusCreditView,
    # ✅ 추가 엔드포인트
    RequiredMissingView,
    DrbolMissingView,
    RequiredRoadmapView,
)

urlpatterns = [
    # 전공/교양 구분
    path('courses/general/<int:user_id>/', GeneralCoursesView.as_view()),
    path('courses/major/<int:user_id>/',   MajorCoursesView.as_view()),

    # 이수율/학점
    path('credit/total/<int:user_id>/',      TotalCreditView.as_view()),
    path('credit/general/<int:user_id>/',    GeneralCreditView.as_view()),
    path('credit/major/<int:user_id>/',      MajorCreditView.as_view()),
    path('credit/statistics/<int:user_id>/', StatisticsCreditView.as_view()),

    # 종합 상태
    path('credit/status/<int:user_id>/',     StatusCreditView.as_view()),

    # ✅ 추가 기능
    path('required/missing/<int:user_id>/',  RequiredMissingView.as_view()),
    path('drbol/missing/<int:user_id>/',     DrbolMissingView.as_view()),
    path('required/roadmap/<int:user_id>/',  RequiredRoadmapView.as_view()),
]