from django.shortcuts import render

# Create your views here.
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from transcripts.models import Transcript
from analysis.models import GraduationRequirement
from users.models import User

import re
import unicodedata


# ---------------------------
# 유틸
# ---------------------------
ROMAN = {"Ⅰ":"1","Ⅱ":"2","Ⅲ":"3","Ⅳ":"4","Ⅴ":"5","Ⅵ":"6","Ⅶ":"7","Ⅷ":"8","Ⅸ":"9"}

def normalize_course_name(name: str) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name)).lower()
    for k, v in ROMAN.items():
        s = s.replace(k, v)
    s = re.sub(r"[·ㆍ\.\-_/]", "", s)
    s = re.sub(r"[\(\)\[\]\{\}\s]+", "", s)
    return s

def course_key_from_dict(d: dict) -> str:
    code = (d.get("code") or "").strip()
    if code:
        return code
    return normalize_course_name(d.get("name", ""))


# ---------------------------
# 공통 헬퍼
# ---------------------------
def get_valid_courses(transcript):
    """
    F 성적 및 재수강 과목 제외한 유효 과목 리스트 반환
    """
    courses = transcript.parsed_data.get("courses", [])
    return [c for c in courses if c.get("grade") != "F" and not c.get("retake", False)]

def semester_sort_key(sem):
    try:
        year, term = map(int, sem.split('-'))
        return (year, term)
    except:
        return (99, 9)


# ---------- 1) 학기별 전체 이수 현황 ----------
class SemesterCourseListView(APIView):
    def get(self, request, user_id):
        transcript = Transcript.objects.filter(user_id=user_id).last()
        if not transcript or not transcript.parsed_data:
            return Response({"error": "성적표 데이터가 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        courses = get_valid_courses(transcript)

        semester_data = {}
        for course in courses:
            sem = course.get("semester", "기타")
            semester_data.setdefault(sem, []).append(course)

        sorted_semesters = sorted(semester_data.keys(), key=semester_sort_key)
        data = {sem: semester_data[sem] for sem in sorted_semesters}
        return Response(data, status=status.HTTP_200_OK)


# ---------- 2) 특정 학기 과목 조회 ----------
class SemesterDetailView(APIView):
    def get(self, request, semester, user_id):
        transcript = Transcript.objects.filter(user_id=user_id).last()
        if not transcript or not transcript.parsed_data:
            return Response({"error": "성적표 데이터가 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        courses = [
            c for c in get_valid_courses(transcript)
            if c.get("semester") == semester
        ]
        return Response({"semester": semester, "courses": courses}, status=status.HTTP_200_OK)


# ---------- 3) 특정 학기의 전공필수 미이수 과목 ----------
class SemesterMissingRequiredView(APIView):
    def get(self, request, semester, user_id):
        transcript = Transcript.objects.filter(user_id=user_id).last()
        if not transcript or not transcript.parsed_data:
            return Response({"error": "성적표 데이터가 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response({"error": "사용자를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        requirement = GraduationRequirement.objects.filter(major=user.major).first()
        if not requirement:
            return Response({"error": "졸업 요건 데이터가 없습니다."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # 완료 과목 키(해당 학기만)
        completed_keys = {
            course_key_from_dict(c)
            for c in get_valid_courses(transcript)
            if c.get("semester") == semester
        }

        # 해당 학기에 계획된 전공필수 중 미이수 (code 기준)
        missing = [
            {"code": (d.get("code") or ""), "name": d.get("name", "")}
            for d in (requirement.major_must_courses or [])
            if (d.get("semester") == semester) and (course_key_from_dict(d) not in completed_keys)
        ]

        return Response({"semester": semester, "missing_required_courses": missing}, status=status.HTTP_200_OK)


# ---------- 4) 전체 보기 + 필터 ----------
class SemesterFilteredView(APIView):
    def get(self, request, user_id):
        transcript = Transcript.objects.filter(user_id=user_id).last()
        if not transcript or not transcript.parsed_data:
            return Response({"error": "성적표 데이터가 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        filter_param = request.GET.get("filter")  # 예: ?filter=전공,교양필수
        courses = get_valid_courses(transcript)

        if filter_param:
            filter_list = [f.strip() for f in filter_param.split(",") if f.strip()]
            courses = [
                c for c in courses
                if any(
                    (f in (c.get("type") or "")) or (f in (c.get("major_field") or ""))
                    for f in filter_list
                )
            ]

        semester_data = {}
        for course in courses:
            sem = course.get("semester", "기타")
            semester_data.setdefault(sem, []).append(course)

        sorted_semesters = sorted(semester_data.keys(), key=semester_sort_key)
        data = {sem: semester_data[sem] for sem in sorted_semesters}
        return Response(data, status=status.HTTP_200_OK)


# ---------- 5) 전체 전공필수 미이수 과목 (플랫) ----------
class MissingAllRequiredCoursesView(APIView):
    """
    모든 학기에 걸친 전공필수 미이수 목록을 플랫 리스트로 반환
    응답 아이템: {code, name, semester}
    """
    def get(self, request, user_id):
        transcript = Transcript.objects.filter(user_id=user_id).last()
        if not transcript or not transcript.parsed_data:
            return Response({"error": "성적표 데이터가 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response({"error": "사용자를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        requirement = GraduationRequirement.objects.filter(major=user.major).first()
        if not requirement:
            return Response({"error": "졸업 요건 데이터가 없습니다."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        completed_keys = {course_key_from_dict(c) for c in get_valid_courses(transcript)}

        missing = [
            {
                "code": (d.get("code") or ""),
                "name": d.get("name", ""),
                "semester": d.get("semester") or "기타",
            }
            for d in (requirement.major_must_courses or [])
            if course_key_from_dict(d) not in completed_keys
        ]

        return Response({"missing_required_courses": missing}, status=status.HTTP_200_OK)


# ---------- 6) 전체 학기별 전공필수 미이수 (by-semester) ----------
class MissingRequiredBySemesterView(APIView):
    """
    모든 학기의 전공필수 미이수를 학기별로 묶어 반환
    응답: {"1-1":[{code,name}], ... , "기타":[...]}
    """
    def get(self, request, user_id):
        transcript = Transcript.objects.filter(user_id=user_id).last()
        if not transcript or not transcript.parsed_data:
            return Response({"error": "성적표 데이터가 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response({"error": "사용자를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        requirement = GraduationRequirement.objects.filter(major=user.major).first()
        if not requirement:
            return Response({"error": "졸업 요건 데이터가 없습니다."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        completed_keys = {course_key_from_dict(c) for c in get_valid_courses(transcript)}

        bucket = {}
        for d in (requirement.major_must_courses or []):
            if course_key_from_dict(d) in completed_keys:
                continue
            sem = d.get("semester") or "기타"
            bucket.setdefault(sem, []).append({
                "code": (d.get("code") or ""),
                "name": d.get("name", "")
            })

        # 정렬된 학기 순서로 재구성
        sorted_sems = sorted(bucket.keys(), key=semester_sort_key)
        data = {sem: bucket[sem] for sem in sorted_sems}
        return Response(data, status=status.HTTP_200_OK)