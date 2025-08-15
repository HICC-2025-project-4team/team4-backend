from rest_framework import generics, status
from rest_framework.response import Response
from collections import defaultdict

# analysis 앱 서비스/헬퍼
from analysis.services import GraduationAnalysisService, _norm_code


# ---------------------------
# 공용: 학기 정렬 키
# 예: "3-1" -> (3, 1), 잘못된 포맷은 뒤로
# ---------------------------
def _semester_sort_key(semester_str: str):
    try:
        y, t = str(semester_str).split("-")
        return int(y), int(t)
    except Exception:
        return (9999, 9999)


# ---------------------------
# 공통 베이스 뷰
# ---------------------------
class BaseSemesterView(generics.GenericAPIView):
    """서비스 클래스를 초기화하고 준비 상태를 확인하는 기본 뷰"""

    def get(self, request, *args, **kwargs):
        user_id = kwargs.get("user_id")
        service = GraduationAnalysisService(user_id)
        if not service.is_ready:
            return Response(
                {"error": "사용자, 성적표 또는 졸업요건 데이터를 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND
            )
        return self.handle_response(request, service, *args, **kwargs)

    def handle_response(self, request, service: GraduationAnalysisService, *args, **kwargs):
        raise NotImplementedError("Subclasses must implement this method")


# ---------------------------
# ✅ 새 API: 수강한 학기 문자열만 반환
# GET /api/semesters/list-only/{user_id}/
# ---------------------------
class SemesterOnlyListView(BaseSemesterView):
    """
    유저가 실제로 수강한 학기 문자열만 리스트로 반환
    (service.valid_courses 기준: F/재수강 제외)
    """
    def handle_response(self, request, service: GraduationAnalysisService, *args, **kwargs):
        semesters = {
            (c.get("semester") or "").strip()
            for c in service.valid_courses
            if c.get("semester")
        }
        semesters.discard("기타")  # 불명확 값 제외
        return Response({"semesters": sorted(semesters, key=_semester_sort_key)})


# ---------------------------
# API 1 & 4. 학기별 전체 이수 현황 (+필터)
# GET /api/semesters/courses/lists/{user_id}/?filter=전공,교양필수,...
# ---------------------------
class SemesterCourseListView(BaseSemesterView):
    def handle_response(self, request, service: GraduationAnalysisService, *args, **kwargs):
        filter_param = request.GET.get("filter")
        courses_to_display = service.valid_courses

        if filter_param:
            # 필터 별칭 정의
            aliases = {
                "drbol": "dr_all", "드볼": "dr_all",
                "major": "major_all", "전공": "major_all",
                "majormust": "major_must", "전공필수": "major_must",
                "majorselect": "major_sel", "전공선택": "major_sel",
                "general": "general_all", "교양": "general_all",
                "generalmust": "gen_must", "교양필수": "gen_must",
                "specialgeneral": "spec_gen", "특성화교양": "spec_gen",
            }
            S = service.req_code_sets
            # 합집합 세트 준비
            S["major_all"] = S["major_must"] | S["major_sel"]
            S["general_all"] = S["gen_must"] | S.get("gen_sel", set()) | S.get("spec_gen", set()) | S["dr_all"]

            wanted_codes = set()
            for token in filter_param.split(','):
                key = aliases.get(token.strip().lower())
                if key and key in S:
                    wanted_codes.update(S[key])

            if wanted_codes:
                courses_to_display = [
                    c for c in service.valid_courses
                    if _norm_code(c.get("code")) in wanted_codes
                ]

        # 학기별 그룹화
        semester_data = defaultdict(list)
        for course in courses_to_display:
            sem = (course.get("semester") or "").strip() or "기타"
            semester_data[sem].append(course)

        # 정렬 + 응답
        sorted_semesters = sorted(semester_data.keys(), key=_semester_sort_key)
        response_data = {sem: semester_data[sem] for sem in sorted_semesters}
        return Response(response_data)


# ---------------------------
# API 2. 특정 학기 상세 과목 리스트
# GET /api/semesters/{semester}/courses/{user_id}/
# ---------------------------
class SemesterDetailView(BaseSemesterView):
    def handle_response(self, request, service: GraduationAnalysisService, *args, **kwargs):
        target_semester = kwargs.get("semester")

        # 해당 학기(F/재수강 제외 규칙)는 service.valid_courses 기준
        raw = [c for c in service.valid_courses if c.get("semester") == target_semester]

        # 필요한 필드만 정리해서 'code' 포함해 반환
        courses = []
        for c in raw:
            # credit은 숫자로 캐스팅 시도
            credit_val = c.get("credit")
            try:
                credit_val = int(credit_val) if credit_val not in (None, "",) else 0
            except Exception:
                credit_val = 0

            courses.append({
                "code":      c.get("code") or "",                             # ✅ 추가됨
                "name":      c.get("name") or c.get("course_name") or "",
                "credit":    credit_val,
                "type":      c.get("type") or c.get("category") or "",
                "grade":     c.get("grade") or "",
                "semester":  c.get("semester") or target_semester,
            })

        return Response({
            "semester": target_semester,
            "count": len(courses),  # 선택: 헤더에 (N과목) 표기용
            "courses": courses
        })



# ---------------------------
# API 3. 특정 학기의 전공필수 미이수
# GET /api/semesters/{semester}/courses/missing-required/{user_id}/
# ---------------------------
class SemesterMissingRequiredView(BaseSemesterView):
    def handle_response(self, request, service: GraduationAnalysisService, *args, **kwargs):
        target_semester = kwargs.get("semester")
        missing_courses = service.analysis_result.get("missing_major_courses", {})
        return Response({
            "semester": target_semester,
            "missing_required_courses": missing_courses.get(target_semester, [])
        })


# ---------------------------
# API 5. 전체 전공필수 미이수 (플랫 리스트)
# GET /api/semesters/courses/missing-required/all/{user_id}/
# ---------------------------
class AllMissingRequiredCoursesView(BaseSemesterView):
    def handle_response(self, request, service: GraduationAnalysisService, *args, **kwargs):
        missing_by_semester = service.analysis_result.get("missing_major_courses", {})
        flat_list = []
        for semester, courses in missing_by_semester.items():
            for course in courses:
                flat_list.append({**course, "semester": semester})
        return Response({"missing_required_courses": flat_list})


# ---------------------------
# API 6. 학기별 전공필수 미이수 타임라인
# GET /api/semesters/courses/missing-required/by-semester/{user_id}/
# ---------------------------
class MissingRequiredBySemesterView(BaseSemesterView):
    def handle_response(self, request, service: GraduationAnalysisService, *args, **kwargs):
        # 요건 상 모든 전공필수 계획 학기를 키로 설정
        all_planned_semesters = {
            item.get("semester", "기타")
            for item in (service.requirement.major_must_courses or [])
        }

        missing_courses = service.analysis_result.get("missing_major_courses", {})
        response_data = {sem: missing_courses.get(sem, []) for sem in all_planned_semesters}

        sorted_sems = sorted(response_data.keys(), key=_semester_sort_key)
        return Response({sem: response_data[sem] for sem in sorted_sems})
