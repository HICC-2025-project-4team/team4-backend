from rest_framework import generics, status
from rest_framework.response import Response
from collections import defaultdict

# analysis 앱의 강력한 서비스 클래스를 임포트합니다.
from analysis.services import GraduationAnalysisService, _norm_code

class BaseSemesterView(generics.GenericAPIView):
    """서비스 클래스를 초기화하고 준비 상태를 확인하는 기본 뷰"""
    def get(self, request, *args, **kwargs):
        user_id = kwargs.get("user_id")
        service = GraduationAnalysisService(user_id)
        if not service.is_ready:
            return Response({"error": "사용자, 성적표 또는 졸업요건 데이터를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)
        return self.handle_response(request, service, *args, **kwargs)

    def handle_response(self, request, service: GraduationAnalysisService, *args, **kwargs):
        raise NotImplementedError("Subclasses must implement this method")

# --- API 1 & 4. 학기별 전체 이수 현황 (+필터) ---
class SemesterCourseListView(BaseSemesterView):
    def handle_response(self, request, service: GraduationAnalysisService, *args, **kwargs):
        filter_param = request.GET.get("filter")
        courses_to_display = service.valid_courses

        if filter_param:
            # 필터링 로직 (서비스에 위임하거나 여기서 직접 구현)
            # 여기서는 analysis 서비스의 코드셋을 활용하여 직접 구현합니다.
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
            S["major_all"] = S["major_must"] | S["major_sel"]
            S["general_all"] = S["gen_must"] | S.get("gen_sel", set()) | S.get("spec_gen", set()) | S["dr_all"]

            wanted_codes = set()
            for token in filter_param.split(','):
                key = aliases.get(token.strip().lower())
                if key and key in S:
                    wanted_codes.update(S[key])
            
            courses_to_display = [c for c in service.valid_courses if _norm_code(c.get("code")) in wanted_codes]

        # 학기별 그룹화
        semester_data = defaultdict(list)
        for course in courses_to_display:
            # 이수 과목에 semester 정보가 없으면 '기타'로 처리
            semester = course.get("semester", "기타")
            semester_data[semester].append(course)

        # 학기 순 정렬
        def semester_sort_key(sem):
            try:
                year, term = map(int, str(sem).split('-'))
                return (year, term)
            except (ValueError, IndexError):
                return (99, 9)
        
        sorted_semesters = sorted(semester_data.keys(), key=semester_sort_key)
        response_data = {sem: semester_data[sem] for sem in sorted_semesters}
        
        return Response(response_data)

# --- API 2. 특정 학기 상세 과목 리스트 ---
class SemesterDetailView(BaseSemesterView):
    def handle_response(self, request, service: GraduationAnalysisService, *args, **kwargs):
        target_semester = kwargs.get("semester")
        courses_in_semester = [
            c for c in service.valid_courses if c.get("semester") == target_semester
        ]
        return Response({
            "semester": target_semester,
            "courses": courses_in_semester
        })

# --- API 3. 특정 학기의 전공필수 미이수 ---
class SemesterMissingRequiredView(BaseSemesterView):
    def handle_response(self, request, service: GraduationAnalysisService, *args, **kwargs):
        target_semester = kwargs.get("semester")
        missing_courses = service.analysis_result.get("missing_major_courses", {})
        
        return Response({
            "semester": target_semester,
            "missing_required_courses": missing_courses.get(target_semester, [])
        })

# --- API 5. 전체 전공필수 미이수 (플랫 리스트) ---
class AllMissingRequiredCoursesView(BaseSemesterView):
    def handle_response(self, request, service: GraduationAnalysisService, *args, **kwargs):
        missing_by_semester = service.analysis_result.get("missing_major_courses", {})
        flat_list = []
        for semester, courses in missing_by_semester.items():
            for course in courses:
                flat_list.append({**course, "semester": semester})
        
        return Response({"missing_required_courses": flat_list})

# --- API 6. 학기별 전공필수 미이수 타임라인 ---
class MissingRequiredBySemesterView(BaseSemesterView):
    def handle_response(self, request, service: GraduationAnalysisService, *args, **kwargs):
        # 졸업요건에 있는 모든 전공필수 학기를 기준으로 응답을 구성
        all_planned_semesters = {
            item.get("semester", "기타") 
            for item in (service.requirement.major_must_courses or [])
        }
        
        missing_courses = service.analysis_result.get("missing_major_courses", {})
        
        response_data = {sem: missing_courses.get(sem, []) for sem in all_planned_semesters}

        # 학기 순 정렬
        def semester_sort_key(sem):
            try:
                year, term = map(int, str(sem).split('-'))
                return (year, term)
            except (ValueError, IndexError):
                return (99, 9)
        
        sorted_semesters = sorted(response_data.keys(), key=semester_sort_key)
        sorted_response = {sem: response_data[sem] for sem in sorted_semesters}

        return Response(sorted_response)