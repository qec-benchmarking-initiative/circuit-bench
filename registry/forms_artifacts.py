from django import forms

from registry.services.artifacts import DEFAULT_MAX_UPLOAD_BYTES, SHA256_PATTERN


class DevelopmentArtifactUploadForm(forms.Form):
    file = forms.FileField(
        help_text=f"Maximum size: {DEFAULT_MAX_UPLOAD_BYTES // 1024} KiB."
    )
    media_type = forms.CharField(
        max_length=255,
        required=False,
        help_text="Defaults to the browser-provided type or application/octet-stream.",
    )
    expected_sha256 = forms.CharField(
        max_length=64,
        required=False,
        help_text="Optional 64-character lowercase SHA-256 assertion.",
    )
    expected_byte_size = forms.IntegerField(
        min_value=0,
        required=False,
        help_text="Optional expected byte size.",
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        if uploaded_file.size > DEFAULT_MAX_UPLOAD_BYTES:
            raise forms.ValidationError(
                f"File exceeds the {DEFAULT_MAX_UPLOAD_BYTES}-byte upload limit."
            )
        return uploaded_file

    def clean_expected_sha256(self):
        expected = self.cleaned_data["expected_sha256"].strip()
        if expected and not SHA256_PATTERN.fullmatch(expected):
            raise forms.ValidationError(
                "Enter 64 lowercase hexadecimal SHA-256 characters."
            )
        return expected or None
