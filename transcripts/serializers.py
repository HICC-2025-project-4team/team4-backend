# transcripts/serializers.py
from rest_framework import serializers
from .models import Transcript, TranscriptPage


class TranscriptUploadSerializer(serializers.ModelSerializer): 
    files = serializers.ListField(
        child=serializers.FileField(),
        allow_empty=False,
        write_only=True
    )

    def create(self, validated_data):
        user = self.context['request'].user
        # validated_data에서 'files'를 분리
        files = validated_data.pop('files')
        
        # Transcript 레코드 생성 (user만으로)
        transcript = Transcript.objects.create(user=user, **validated_data)

        # 페이지별 파일 저장
        for idx, f in enumerate(files, start=1):
            TranscriptPage.objects.create(
                transcript=transcript,
                file=f,
                page_number=idx
            )
        return transcript
    
    class Meta:
        model = Transcript
        # 이제 이 필드들이 정상적으로 응답에 포함됩니다.
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
        