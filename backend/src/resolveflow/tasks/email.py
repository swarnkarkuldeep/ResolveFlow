from resolveflow.celery_app import celery
from resolveflow.config import get_settings
from resolveflow.email.outbound import get_provider


@celery.task(
    name="resolveflow.tasks.email.send_invitation",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=5,
)
def send_invitation(to: str, workspace_name: str, inviter_name: str, token: str) -> None:
    link = f"{get_settings().public_base_url}/accept-invite?token={token}"
    get_provider().send(
        to=to,
        subject=f"{inviter_name} invited you to {workspace_name} on ResolveFlow",
        text=(
            f"{inviter_name} invited you to join {workspace_name} on ResolveFlow.\n\n"
            f"Accept the invitation and set your password:\n{link}\n\n"
            "The link works once and expires in 7 days."
        ),
    )
