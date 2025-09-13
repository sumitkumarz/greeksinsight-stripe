from app.config import Config

def remove_user_from_group(user_name, group_name):
    cognito = Config.COGNITO_CLIENT
    USER_POOL_ID = Config.USER_POOL_ID
    try:
        cognito.admin_remove_user_from_group(
            UserPoolId=USER_POOL_ID,
            Username=user_name,
            GroupName=group_name
        )
    except cognito.exceptions.UserNotFoundException:
        pass

def add_user_to_group(user_name, group_name):
    cognito = Config.COGNITO_CLIENT
    USER_POOL_ID = Config.USER_POOL_ID
    cognito.admin_add_user_to_group(
        UserPoolId=USER_POOL_ID,
        Username=user_name,
        GroupName=group_name
    )
