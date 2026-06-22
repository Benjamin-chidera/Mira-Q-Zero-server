import pytest
from unittest.mock import MagicMock, patch
from sqlmodel import Session, select
from utils.mira.ai_research_models import ResearchConversation, ResearchMessage
from utils.mira.ai_research import get_cache_key

def test_research_center_status_and_delete(client, session: Session):
    # 1. Arrange: Create a practitioner user first
    from models import User
    user = User(
        email="test_doc@gpconnect.nhs.uk",
        name="Test Doctor",
        role="practitioner",
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    # Insert a conversation
    conv = ResearchConversation(
        id="test_conv_123",
        practitioner_id=user.id,
        title="Test Research",
        preview="No messages yet",
        status="Ongoing"
    )
    session.add(conv)
    session.commit()
    session.refresh(conv)

    # 2. Act: PATCH the status to Completed
    response = client.patch(
        f"/mira/research/conversations/{conv.id}/status",
        json={"status": "Completed"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "Completed"
    assert data["status_reason"] is None

    # Check database
    session.refresh(conv)
    assert conv.status == "Completed"

    # 3. Act: PATCH the status to Failed with a reason
    response = client.patch(
        f"/mira/research/conversations/{conv.id}/status",
        json={"status": "Failed", "reason": "No relevant studies found"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "Failed"
    assert data["status_reason"] == "No relevant studies found"

    # Check database
    session.refresh(conv)
    assert conv.status == "Failed"
    assert conv.status_reason == "No relevant studies found"

    # 4. Act: GET conversations and verify status is returned
    response = client.get(f"/mira/research/conversations?practitioner_id={user.id}")
    assert response.status_code == 200
    convs_list = response.json()
    assert len(convs_list) > 0
    assert convs_list[0]["status"] == "Failed"
    assert convs_list[0]["status_reason"] == "No relevant studies found"

    # 5. Act: DELETE conversation with a reason
    response = client.delete(
        f"/mira/research/conversations/{conv.id}?reason=Doctor requested delete"
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Conversation deleted successfully"

    # Check database (it should be deleted)
    deleted_conv = session.get(ResearchConversation, conv.id)
    assert deleted_conv is None

@patch("utils.mira.ai_research.redis_client")
def test_redis_cache_key_and_hitting(mock_redis_client):
    # Test cache key generation
    key1 = get_cache_key("Thyroidectomy in Lupus", [{"type": "pdf", "name": "report.pdf", "url": "http://example.com/pdf"}])
    key2 = get_cache_key("Thyroidectomy in Lupus", [{"type": "pdf", "name": "report.pdf", "url": "http://example.com/pdf"}])
    assert key1 == key2

    # Different inputs should yield different keys
    key3 = get_cache_key("Thyroidectomy in Lupus", [])
    assert key1 != key3
