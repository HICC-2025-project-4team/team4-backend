# transcripts/serializers.py
from rest_framework import serializers
from .models import Transcript

class TranscriptUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transcript
        fields = ['id', 'file']
        read_only_fields = ['id']

    def create(self, validated_data):
        # user 를 view 에서 할당
        return Transcript.objects.create(**validated_data)

class TranscriptStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transcript
        fields = ['id', 'status', 'error_message']

class TranscriptParsedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transcript
        fields = ['id', 'parsed']
