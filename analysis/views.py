from rest_framework import generics, permissions, status
from rest_framework.response import Response
from .services import GraduationAnalysisService

class BaseAnalysisView(generics.GenericAPIView):
    """서비스 클래스를 초기화하고 준비 상태를 확인하는 기본 뷰"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        service = GraduationAnalysisService(kwargs.get("user_id"))
        if not service.is_ready:
            return Response({"error": "사용자, 성적표 또는 졸업요건 데이터를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)
        return self.handle_response(service)

    def handle_response(self, service: GraduationAnalysisService):
        raise NotImplementedError("Subclasses must implement this method")

class GeneralCoursesView(BaseAnalysisView):
    def handle_response(self, service):
        return Response(service.get_general_courses_status())

class MajorCoursesView(BaseAnalysisView):
    def handle_response(self, service):
        return Response(service.get_major_courses_status())

class TotalCreditView(BaseAnalysisView):
    def handle_response(self, service):
        return Response({"total_credit": service.analysis_result.get("total_completed", 0)})

class GeneralCreditView(BaseAnalysisView):
    def handle_response(self, service):
        return Response({"general_credit": service.analysis_result.get("general_completed", 0)})

class MajorCreditView(BaseAnalysisView):
    def handle_response(self, service):
        return Response({"major_credit": service.analysis_result.get("major_completed", 0)})

class StatisticsCreditView(BaseAnalysisView):
    def handle_response(self, service):
        return Response(service.get_credit_statistics())

class GraduationStatusView(BaseAnalysisView):
    def handle_response(self, service):
        # 7번 API는 분석 결과 전체를 반환
        return Response(service.analysis_result)

class RequiredMissingView(BaseAnalysisView):
    def handle_response(self, service):
        # 8번 API는 서비스에서 별도로 조합
        major_missing = service.analysis_result.get('missing_major_courses', {})
        flat_major_missing = []
        for sem, courses in major_missing.items():
            for c in courses: flat_major_missing.append({**c, "semester": sem})
        
        # 교양 미이수 로직 추가
        general_status = service.get_general_courses_status()
        general_missing = []
        if not general_status['이수여부']:
             # 서비스에서 미이수 그룹 정보를 가져오도록 수정 필요
             pass

        return Response({
            "major_required_missing": flat_major_missing,
            "general_required_missing": general_missing # TODO
        })

class DrbolMissingView(BaseAnalysisView):
    def handle_response(self, service):
        return Response(service.get_drbol_status())

class RequiredRoadmapView(BaseAnalysisView):
    def handle_response(self, service):
        return Response(service.get_required_roadmap())