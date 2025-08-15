from django.urls import path
from .views import (
    GeneralCoursesView,
    MajorCoursesView,
    TotalCreditView,
    GeneralCreditView,
    MajorCreditView,
    CreditStatusView,
    StatisticsCreditView,
    GraduationStatusView,
    RequiredMissingView,
    DrbolMissingView,
    RequiredRoadmapView,
)

app_name = 'analysis'

urlpatterns = [
    # 1) 교양/전공 필수 이수 여부
    path('courses/general/<int:user_id>/', GeneralCoursesView.as_view(), name='courses_general'),
    path('courses/major/<int:user_id>/', MajorCoursesView.as_view(), name='courses_major'),

    # 3-5) 학점 조회
    path('credit/total/<int:user_id>/', TotalCreditView.as_view(), name='credit_total'),
    path('credit/general/<int:user_id>/', GeneralCreditView.as_view(), name='credit_general'),
    path('credit/major/<int:user_id>/', MajorCreditView.as_view(), name='credit_major'),
    path('credit/part/<int:user_id>/', CreditStatusView.as_view()),

    # 6) 이수율 시각화
    path('credit/statistics/<int:user_id>/', StatisticsCreditView.as_view(), name='credit_statistics'),

    # 7) 졸업요건 충족 여부
    path('credit/status/<int:user_id>/', GraduationStatusView.as_view(), name='graduation_status'),
    
    # 8) 전체 미이수 필수 과목
    path('required/missing/<int:user_id>/', RequiredMissingView.as_view(), name='required_missing'),
    
    # 9) 미이수 드볼 영역
    path('drbol/missing/<int:user_id>/', DrbolMissingView.as_view(), name='drbol_missing'),

    # 10) 필수 과목 로드맵
    path('required/roadmap/<int:user_id>/', RequiredRoadmapView.as_view(), name='required_roadmap'),
]