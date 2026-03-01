from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.db import transaction, IntegrityError
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils import timezone
import os
from .models import User, College, OneTimePassword, Shop, MenuItem, Order, DeviceToken
from .serializers import (
    UserRegisterSerializer,
    LoginSerializer,
    LogoutUserSerializer,
    CollegeSerializer,
    AdminCreateECardSerializer,
    MyCardSerializer,
    ShopSerializer,
    AdminShopCreateSerializer,
    MenuItemSerializer,
    OrderSerializer,
    PlaceOrderSerializer,
)


# Try to import Firebase Admin for FCM HTTP v1
try:
    import firebase_admin  # type: ignore
    from firebase_admin import messaging  # type: ignore
except Exception:  # pragma: no cover
    firebase_admin = None
    messaging = None


def _send_fcm(tokens: list[str], *, title: str, body: str, data: dict) -> None:
    """Send FCM notifications preferring HTTP v1 via firebase_admin.messaging.
    Falls back to legacy HTTP API if Admin SDK is not available.
    """
    if not tokens:
        return
    # Prefer HTTP v1 if Admin SDK is available and initialized
    try:
        if firebase_admin and messaging and getattr(firebase_admin, "_apps", None):
            msg = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                tokens=tokens,
                data={k: str(v) for k, v in (data or {}).items()},
            )
            messaging.send_multicast(msg, dry_run=False)
            return
    except Exception:
        # Fall through to legacy HTTP
        pass

    # Legacy HTTP fallback (deprecated) – will work until fully shut down
    try:
        import requests  # local import to avoid hard dep if not needed
        from django.conf import settings
        server_key = getattr(settings, 'FCM_SERVER_KEY', None)
        if not server_key:
            return
        headers = {
            'Authorization': f'key {server_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'registration_ids': tokens,
            'notification': {
                'title': title,
                'body': body,
            },
            'data': data or {},
        }
        requests.post('https://fcm.googleapis.com/fcm/send', json=payload, headers=headers, timeout=5)
    except Exception:
        pass


class RegisterUserView(GenericAPIView):
    serializer_class = UserRegisterSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        data = {
            "id": user.id,
            "name": user.name,
            "username": user.username,
            "role": user.role,
            "email": user.email,
        }
        return Response({"data": data, "message": "Signup successful"}, status=status.HTTP_201_CREATED)


class VerifyUserEmail(GenericAPIView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def post(self, request):
        otpcode = request.data.get("otp")
        college_name = request.data.get("college_name")
        if not otpcode:
            return Response({"message": "OTP is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            otp_obj = OneTimePassword.objects.select_related("user").get(code=otpcode)
        except OneTimePassword.DoesNotExist:
            return Response({"message": "invalid otp"}, status=status.HTTP_404_NOT_FOUND)

        user = otp_obj.user
        if getattr(user, "is_email_verified", False):
            return Response({"message": "user already verified"}, status=status.HTTP_200_OK)

        user.is_email_verified = True
        user.save(update_fields=["is_email_verified"]) 

        # If admin, create college now
        if user.role == User.ROLE_ADMIN and college_name:
            domain = None
            if user.email and "@" in user.email:
                domain = user.email.split("@")[-1].lower()
            try:
                college, created = College.objects.get_or_create(
                    name=college_name,
                    defaults={"domain": domain, "created_by": user},
                )
            except IntegrityError:
                # Likely due to unique domain constraint collision
                return Response(
                    {"message": "A college with this email domain is already registered. Please use a different admin email domain or college name."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if created:
                user.college = college
                user.save(update_fields=["college"]) 

        return Response({"message": "account email verified successfully"}, status=status.HTTP_200_OK)


class LoginUserView(GenericAPIView):
    serializer_class = LoginSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class LogoutUserView(GenericAPIView):
    serializer_class = LogoutUserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_200_OK)


class CollegeListView(GenericAPIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = College.objects.all().order_by('name')
        data = CollegeSerializer(qs, many=True).data
        return Response(data, status=status.HTTP_200_OK)


class AdminCreateECardView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = AdminCreateECardSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(result, status=status.HTTP_201_CREATED)


class MyCardView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        data = MyCardSerializer.from_user(user)
        return Response(data, status=status.HTTP_200_OK)


class AdminShopListCreateView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]

    def get(self, request):
        admin_user: User = request.user
        if not admin_user.college:
            return Response({"detail": "Admin is not associated with any college."}, status=status.HTTP_400_BAD_REQUEST)
        qs = Shop.objects.filter(college=admin_user.college, is_active=True).select_related('owner').order_by('-created_at')
        return Response(ShopSerializer(qs, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = AdminShopCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.save()
        return Response(data, status=status.HTTP_201_CREATED)


class OwnerMenuListCreateView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user: User = request.user
        if user.role != User.ROLE_OWNER:
            return Response({"detail": "Only shop owners can access this endpoint."}, status=status.HTTP_403_FORBIDDEN)
        try:
            shop = Shop.objects.get(owner=user)
        except Shop.DoesNotExist:
            return Response({"detail": "Shop not found for this owner."}, status=status.HTTP_404_NOT_FOUND)
        items = shop.menu_items.all().order_by('name')
        return Response(MenuItemSerializer(items, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        user: User = request.user
        if user.role != User.ROLE_OWNER:
            return Response({"detail": "Only shop owners can access this endpoint."}, status=status.HTTP_403_FORBIDDEN)
        try:
            shop = Shop.objects.get(owner=user)
        except Shop.DoesNotExist:
            return Response({"detail": "Shop not found for this owner."}, status=status.HTTP_404_NOT_FOUND)
        serializer = MenuItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = MenuItem.objects.create(
            shop=shop,
            name=serializer.validated_data['name'],
            price=serializer.validated_data['price'],
            image_url=serializer.validated_data.get('image_url'),
            is_active=serializer.validated_data.get('is_active', True),
        )
        return Response(MenuItemSerializer(item).data, status=status.HTTP_201_CREATED)


class OwnerMenuItemDetailView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, item_id: int):
        user: User = request.user
        if user.role != User.ROLE_OWNER:
            return Response({"detail": "Only shop owners can access this endpoint."}, status=status.HTTP_403_FORBIDDEN)
        try:
            shop = Shop.objects.get(owner=user)
        except Shop.DoesNotExist:
            return Response({"detail": "Shop not found for this owner."}, status=status.HTTP_404_NOT_FOUND)
        try:
            item = MenuItem.objects.get(id=item_id, shop=shop)
        except MenuItem.DoesNotExist:
            return Response({"detail": "Menu item not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = MenuItemSerializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(item, field, value)
        item.save()
        return Response(MenuItemSerializer(item).data, status=status.HTTP_200_OK)

    def delete(self, request, item_id: int):
        user: User = request.user
        if user.role != User.ROLE_OWNER:
            return Response({"detail": "Only shop owners can access this endpoint."}, status=status.HTTP_403_FORBIDDEN)
        try:
            shop = Shop.objects.get(owner=user)
        except Shop.DoesNotExist:
            return Response({"detail": "Shop not found for this owner."}, status=status.HTTP_404_NOT_FOUND)
        try:
            item = MenuItem.objects.get(id=item_id, shop=shop)
        except MenuItem.DoesNotExist:
            return Response({"detail": "Menu item not found."}, status=status.HTTP_404_NOT_FOUND)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ShopMenuPublicView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user: User = request.user
        if not user.college:
            return Response({"detail": "User is not associated with any college."}, status=status.HTTP_400_BAD_REQUEST)
        code = request.query_params.get('code')
        name = request.query_params.get('name')
        if not code and not name:
            return Response({"detail": "Provide shop 'code' or 'name' as query param."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            if code:
                shop = Shop.objects.get(code=code, college=user.college)
            else:
                shop = Shop.objects.get(name=name, college=user.college)
        except Shop.DoesNotExist:
            return Response({"detail": "Shop not found in your college."}, status=status.HTTP_404_NOT_FOUND)
        items = shop.menu_items.filter(is_active=True).order_by('name')
        return Response(MenuItemSerializer(items, many=True).data, status=status.HTTP_200_OK)

    # No POST here; admin should create shops via /auth/shops/


class AdminShopDeleteView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]

    def delete(self, request, pk: int):
        admin_user: User = request.user
        if not admin_user.college:
            return Response({"detail": "Admin is not associated with any college."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            shop = Shop.objects.select_related('owner', 'college').get(id=pk, college=admin_user.college)
        except Shop.DoesNotExist:
            return Response({"detail": "Shop not found in your college."}, status=status.HTTP_404_NOT_FOUND)

        # Delete shop and its owner within a transaction
        with transaction.atomic():
            owner = shop.owner
            shop.delete()
            if owner and owner.role == User.ROLE_OWNER:
                owner.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OwnerMyShopView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user: User = request.user
        if user.role != User.ROLE_OWNER:
            return Response({"detail": "Only shop owners can access this endpoint."}, status=status.HTTP_403_FORBIDDEN)
        try:
            shop = Shop.objects.select_related('owner').get(owner=user)
        except Shop.DoesNotExist:
            return Response({"detail": "Shop not found for this owner."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ShopSerializer(shop).data, status=status.HTTP_200_OK)


class OwnerUploadImageView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user: User = request.user
        if user.role != User.ROLE_OWNER:
            return Response({"detail": "Only shop owners can upload images."}, status=status.HTTP_403_FORBIDDEN)
        try:
            shop = Shop.objects.get(owner=user)
        except Shop.DoesNotExist:
            return Response({"detail": "Shop not found for this owner."}, status=status.HTTP_404_NOT_FOUND)

        f = request.FILES.get('image')
        if not f:
            return Response({"detail": "No image uploaded. Use form-data field 'image'."}, status=status.HTTP_400_BAD_REQUEST)

        # Build a safe path: uploads/menu/<shop_code>/YYYY/MM/DD/<timestamp>_<filename>
        today = timezone.now()
        folder = os.path.join('uploads', 'menu', shop.code, str(today.year), f"{today.month:02d}", f"{today.day:02d}")
        filename = f"{int(today.timestamp())}_{f.name}"
        path = os.path.join(folder, filename)
        saved_path = default_storage.save(path, ContentFile(f.read()))
        try:
            url = default_storage.url(saved_path)
        except Exception:
            url = f"/media/{saved_path}"

        # Ensure absolute URL so clients and URL validators accept it
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                absolute_url = request.build_absolute_uri(url)
            else:
                absolute_url = url
        except Exception:
            absolute_url = request.build_absolute_uri(url)

        return Response({"url": absolute_url}, status=status.HTTP_201_CREATED)


class GlobalSearchView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user: User = request.user
        q = (request.query_params.get('q') or '').strip()
        if not q:
            return Response({"shops": [], "items": []}, status=status.HTTP_200_OK)
        if not user.college:
            return Response({"detail": "User is not associated with any college."}, status=status.HTTP_400_BAD_REQUEST)

        shops_qs = Shop.objects.filter(college=user.college, is_active=True, name__icontains=q).order_by('name')[:20]
        items_qs = MenuItem.objects.select_related('shop').filter(
            shop__college=user.college,
            shop__is_active=True,
            is_active=True,
            name__icontains=q,
        ).order_by('name')[:20]

        shops = [
            {"id": s.id, "name": s.name, "code": s.code}
            for s in shops_qs
        ]
        items = [
            {"id": m.id, "name": m.name, "price": str(m.price), "shop_id": m.shop_id, "shop_name": m.shop.name, "shop_code": m.shop.code}
            for m in items_qs
        ]

        return Response({"shops": shops, "items": items}, status=status.HTTP_200_OK)


class StudentOrdersView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user: User = request.user
        if user.role != User.ROLE_STUDENT:
            return Response({"detail": "Only students can view their orders."}, status=status.HTTP_403_FORBIDDEN)
        qs = Order.objects.filter(student=user).prefetch_related('items', 'shop').order_by('-created_at')
        return Response(OrderSerializer(qs, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = PlaceOrderSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        # Try to send push to owner
        try:
            self._notify_owner_new_order(order)
        except Exception:
            pass
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _notify_owner_new_order(order: Order):
        owner = order.shop.owner
        if not owner:
            return
        tokens = list(DeviceToken.objects.filter(user=owner).values_list('token', flat=True))
        if not tokens:
            return
        title = 'New Order'
        body = f'Order #{order.id} - ₹{order.total_amount} from {order.student.name}'
        data = {
            'type': 'NEW_ORDER',
            'order_id': order.id,
            'shop_name': order.shop.name,
        }
        _send_fcm(tokens, title=title, body=body, data=data)


class StudentOrderCancelView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, order_id: int):
        user: User = request.user
        if user.role != User.ROLE_STUDENT:
            return Response({"detail": "Only students can cancel their orders."}, status=status.HTTP_403_FORBIDDEN)
        try:
            order = Order.objects.select_related('shop', 'student').get(id=order_id)
        except Order.DoesNotExist:
            return Response({"detail": "Order not found"}, status=status.HTTP_404_NOT_FOUND)
        if order.status != Order.STATUS_PENDING:
            return Response({"detail": "You can only cancel a pending order."}, status=status.HTTP_400_BAD_REQUEST)
        order.status = Order.STATUS_CANCELLED
        order.save(update_fields=["status", "updated_at"])
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)


class OwnerOrdersView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user: User = request.user
        if user.role != User.ROLE_OWNER:
            return Response({"detail": "Only shop owners can view shop orders."}, status=status.HTTP_403_FORBIDDEN)
        try:
            shop = Shop.objects.get(owner=user)
        except Shop.DoesNotExist:
            return Response({"detail": "Shop not found for this owner."}, status=status.HTTP_404_NOT_FOUND)
        qs = Order.objects.filter(shop=shop).exclude(status=Order.STATUS_CANCELLED).prefetch_related('items', 'student').order_by('-created_at')
        return Response(OrderSerializer(qs, many=True).data, status=status.HTTP_200_OK)


class OwnerOrderDetailView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, order_id: int):
        user: User = request.user
        if user.role != User.ROLE_OWNER:
            return Response({"detail": "Only shop owners can update orders."}, status=status.HTTP_403_FORBIDDEN)
        try:
            shop = Shop.objects.get(owner=user)
        except Shop.DoesNotExist:
            return Response({"detail": "Shop not found for this owner."}, status=status.HTTP_404_NOT_FOUND)
        try:
            order = Order.objects.get(id=order_id, shop=shop)
        except Order.DoesNotExist:
            return Response({"detail": "Order not found."}, status=status.HTTP_404_NOT_FOUND)

        allowed_status = {c[0] for c in Order.STATUS_CHOICES}
        # Track previous values to detect changes
        prev_status = order.status
        prev_paid = bool(order.is_paid)
        prev_picked = bool(order.is_picked)

        next_status = request.data.get('status')
        is_paid = request.data.get('is_paid')
        is_picked = request.data.get('is_picked')

        # Simple transition checks (optional)
        if next_status:
            if next_status not in allowed_status:
                return Response({"detail": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)
            # You can enforce simple flow, e.g., pending->preparing->ready->completed
            order.status = next_status

        if isinstance(is_paid, bool):
            order.is_paid = is_paid
        if isinstance(is_picked, bool):
            # Enforce: can only pick after payment
            if is_picked and not (order.is_paid or (is_paid is True)):
                return Response({"detail": "Order must be marked as paid before it can be picked."}, status=status.HTTP_400_BAD_REQUEST)
            order.is_picked = is_picked

        order.save(update_fields=['status', 'is_paid', 'is_picked', 'updated_at'])
        # Try to notify student about updates
        try:
            # Status changed
            if order.status != prev_status:
                self._notify_student_status_update(order)
            # Payment received
            if (not prev_paid) and order.is_paid:
                self._notify_student_custom(order, title='Payment Received', body=f"Payment received for order #{order.id}", data={
                    'type': 'ORDER_PAID',
                    'order_id': order.id,
                    'status': order.status,
                    'shop_name': order.shop.name,
                })
            # Order picked up
            if (not prev_picked) and order.is_picked:
                self._notify_student_custom(order, title='Order Picked Up', body=f"You picked up order #{order.id}", data={
                    'type': 'ORDER_PICKED',
                    'order_id': order.id,
                    'status': order.status,
                    'shop_name': order.shop.name,
                })
        except Exception:
            pass
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)

    @staticmethod
    def _notify_student_status_update(order: Order):
        student = order.student
        tokens = list(DeviceToken.objects.filter(user=student).values_list('token', flat=True))
        if not tokens:
            return
        title = 'Order Update'
        body = f"Your order #{order.id} is now {order.status.capitalize()}"
        data = {
            'type': 'ORDER_STATUS',
            'order_id': order.id,
            'status': order.status,
            'shop_name': order.shop.name,
        }
        _send_fcm(tokens, title=title, body=body, data=data)

    @staticmethod
    def _notify_student_custom(order: Order, *, title: str, body: str, data: dict):
        student = order.student
        tokens = list(DeviceToken.objects.filter(user=student).values_list('token', flat=True))
        if not tokens:
            return
        _send_fcm(tokens, title=title, body=body, data=data)


class RegisterDeviceTokenView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        token = request.data.get('token')
        platform = request.data.get('platform')
        if not token:
            return Response({"detail": "token required"}, status=status.HTTP_400_BAD_REQUEST)
        DeviceToken.objects.update_or_create(user=request.user, token=token, defaults={'platform': platform})
        return Response(status=status.HTTP_204_NO_CONTENT)


class CollegeShopsListView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user: User = request.user
        if not user.college:
            return Response({"detail": "User is not associated with any college."}, status=status.HTTP_400_BAD_REQUEST)
        qs = Shop.objects.filter(college=user.college, is_active=True).select_related('owner').order_by('name')
        return Response(ShopSerializer(qs, many=True).data, status=status.HTTP_200_OK)

    def patch(self, request):
        user: User = request.user
        if user.role != User.ROLE_OWNER:
            return Response({"detail": "Only shop owners can access this endpoint."}, status=status.HTTP_403_FORBIDDEN)
        try:
            shop = Shop.objects.get(owner=user)
        except Shop.DoesNotExist:
            return Response({"detail": "Shop not found for this owner."}, status=status.HTTP_404_NOT_FOUND)
        name = request.data.get('name')
        if name and isinstance(name, str) and name.strip():
            shop.name = name.strip()
            shop.save(update_fields=['name', 'updated_at'])
        return Response(ShopSerializer(shop).data, status=status.HTTP_200_OK)