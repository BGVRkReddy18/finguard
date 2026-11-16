from rest_framework import generics

from .models import User
from .permissions import IsManagerOrAdmin
from .serializers import UserSerializer


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class UserListView(generics.ListAPIView):
    """Managers use this to pick an analyst when assigning cases."""

    serializer_class = UserSerializer
    permission_classes = [IsManagerOrAdmin]
    queryset = User.objects.filter(is_active=True).order_by("username")
