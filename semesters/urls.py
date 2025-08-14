from django.urls import path
from .views import (
    SemesterCourseListView,
    SemesterDetailView,
    SemesterMissingRequiredView,
    AllMissingRequiredCoursesView,
    MissingRequiredBySemesterView,
)

app_name = 'semesters'

urlpatterns = [
    # [수정] API 명세서 1번과 4번을 모두 처리하는 URL
    # GET /api/semesters/1/ -> 필터 없는 전체 목록
    # GET /api/semesters/1/?filter=전공 -> 필터링된 목록
    path('<int:user_id>/', SemesterCourseListView.as_view(), name='semester_course_list'),

    # 2) 특정 학기 상세 과목 리스트
    path('<str:semester>/courses/<int:user_id>/', SemesterDetailView.as_view(), name='semester_detail'),

    # 3) 특정 학기의 전공필수 미이수
    path('<str:semester>/missing-required/<int:user_id>/', SemesterMissingRequiredView.as_view(), name='semester_missing_required'),

    # 5) 전체 전공필수 미이수 (플랫 리스트)
    path('courses/missing-required/all/<int:user_id>/', AllMissingRequiredCoursesView.as_view(), name='all_missing_required'),

    # 6) 학기별 전공필수 미이수 타임라인
    path('courses/missing-required/by-semester/<int:user_id>/', MissingRequiredBySemesterView.as_view(), name='missing_required_by_semester'),
]