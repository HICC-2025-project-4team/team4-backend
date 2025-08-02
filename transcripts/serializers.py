# transcripts/serializers.py
from rest_framework import serializers
from .models import Transcript, TranscriptPage


class TranscriptUploadSerializer(serializers.Serializer):
    files = serializers.ListField(
        child=serializers.FileField(),
        allow_empty=False,
        write_only=True
    )

    def create(self, validated_data):
        user = self.context['request'].user
        # 1) Transcript 레코드 생성
        transcript = Transcript.objects.create(user=user)
        # 2) 페이지별 파일 저장
        for idx, f in enumerate(validated_data['files'], start=1):
            TranscriptPage.objects.create(
                transcript=transcript,
                file=f,
                page_number=idx
            )
        return transcript
    
    class Meta:
        model = Transcript
        # 클라이언트에 리턴해줄 필드들
        fields = ['id', 'files', 'status', 'created_at']
        read_only_fields = ['id', 'status', 'created_at']

class TranscriptStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transcript
        fields = ['id', 'status', 'error_message']

class TranscriptParsedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transcript
        fields = ['id', 'parsed_data']
        