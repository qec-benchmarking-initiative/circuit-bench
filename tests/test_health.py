import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health_checks_postgresql(client):
    response = client.get(reverse("pages:health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}

