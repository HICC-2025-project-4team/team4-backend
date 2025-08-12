from django.urls import path
from .views import (
    SemesterCourseListView, SemesterDetailView, SemesterMissingRequiredView,
    SemesterFilteredView, MissingAllRequiredCoursesView, MissingRequiredBySemesterView
)

urlpatterns = [
    path('courses/lists/<int:user_id>/', SemesterCourseListView.as_view()),
    path('<str:semester>/courses/<int:user_id>/', SemesterDetailView.as_view()),
    path('<str:semester>/courses/missing-required/<int:user_id>/', SemesterMissingRequiredView.as_view()),
    path('<int:user_id>/', SemesterFilteredView.as_view()),
    path('courses/missing-required/all/<int:user_id>/', MissingAllRequiredCoursesView.as_view()),
    path('courses/missing-required/by-semester/<int:user_id>/', MissingRequiredBySemesterView.as_view()),  # ✅ 추가
]