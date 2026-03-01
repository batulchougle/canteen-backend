from rest_framework import serializers
from django.db import transaction
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from .models import User, College, ECanteenCard, Shop, MenuItem, Order, OrderItem, DeviceToken
from .utility import send_code_to_user
from django.utils import timezone


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(max_length=68, min_length=6, write_only=True)
    password2 = serializers.CharField(max_length=68, min_length=6, write_only=True)
    role = serializers.ChoiceField(choices=User.ROLE_CHOICES)
    college_name = serializers.CharField(required=False, allow_blank=True)
    ecard_code = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ['email', 'name', 'username', 'password', 'password2', 'role', 'college_name', 'ecard_code']

    def validate(self, attrs):
        password = attrs.get('password', '')
        password2 = attrs.get('password2', '')
        username = attrs.get('username')
        email = attrs.get('email')
        role = attrs.get('role')
        ecard_code = attrs.get('ecard_code')
        college_name = attrs.get('college_name')

        errors = {}

        if password != password2:
            errors['password'] = 'Passwords did not match'

        if User.objects.filter(username=username).exists():
            errors['username'] = 'This username is already taken.'

        if email and User.objects.filter(email=email).exists():
            errors['email'] = 'You already have an account. Try to login.'

        if role == User.ROLE_ADMIN and not email:
            errors['email'] = 'Admin signup requires email.'

        if role in (User.ROLE_STUDENT, User.ROLE_OWNER):
            # Require pre-registered e-canteen card
            if not ecard_code:
                errors['ecard_code'] = 'Signup requires a valid e-canteen card code.'
            else:
                ecard_code = ecard_code.strip().upper()
                attrs['ecard_code'] = ecard_code
                try:
                    card = ECanteenCard.objects.select_related('college').get(code=ecard_code)
                    if not card.is_valid():
                        errors['ecard_code'] = 'This code is not valid or already used.'
                    elif (role == User.ROLE_STUDENT and card.role != User.ROLE_STUDENT) or (role == User.ROLE_OWNER and card.role != User.ROLE_OWNER):
                        errors['ecard_code'] = 'Code role mismatch.'
                    else:
                        # If client provided college_name, enforce that it matches the code's college
                        if college_name:
                            provided = college_name.strip().lower()
                            actual = (card.college.name or '').strip().lower()
                            if provided != actual:
                                errors['college_name'] = 'Selected college does not match the e-canteen card. Please select the correct college.'
                except ECanteenCard.DoesNotExist:
                    errors['ecard_code'] = 'Invalid e-canteen card code.'

        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def create(self, validated_data):
        role = validated_data.get('role')
        college_name = validated_data.pop('college_name', None)
        ecard_code = validated_data.pop('ecard_code', None)
        password = validated_data.pop('password')
        validated_data.pop('password2', None)

        if role == User.ROLE_ADMIN:
            # Create admin user with email verification pending
            user = User.signup_admin(
                name=validated_data.get('name'),
                username=validated_data.get('username'),
                password=password,
                email=validated_data.get('email'),
                college=None,
            )
            user.is_email_verified = False
            user.save(update_fields=['is_email_verified'])
            # Send OTP to admin email
            send_code_to_user(user.email, user)
            # Optionally store intended college_name in context or return to be used in verify step
            self.context['college_name'] = college_name
            return user

        if role == User.ROLE_STUDENT:
            # attach college from valid card and mark used
            with transaction.atomic():
                card = ECanteenCard.objects.select_related('college').select_for_update().get(code=ecard_code)
                user = User.signup_student(
                    name=validated_data.get('name'),
                    username=validated_data.get('username'),
                    password=password,
                    college=card.college,
                )
                user.ecard_code = ecard_code
                user.save(update_fields=["ecard_code"])
                card.is_used = True
                card.save(update_fields=['is_used'])
                return user

        # owner
        with transaction.atomic():
            card = ECanteenCard.objects.select_related('college').select_for_update().get(code=ecard_code)
            user = User.signup_owner(
                name=validated_data.get('name'),
                username=validated_data.get('username'),
                password=password,
                college=card.college,
            )
            user.ecard_code = ecard_code
            user.save(update_fields=["ecard_code"])
            card.is_used = True
            card.save(update_fields=['is_used'])
            # If a shop was pre-created by admin with this owner card, link it now
            try:
                from .models import Shop
                shop = Shop.objects.select_for_update().get(pending_owner_ecard_code=ecard_code, college=user.college)
                shop.owner = user
                shop.pending_owner_ecard_code = None
                if not shop.owner_display_name:
                    shop.owner_display_name = user.name
                shop.save(update_fields=["owner", "pending_owner_ecard_code", "owner_display_name", "updated_at"])
            except Exception:
                pass
            return user

class MyCardSerializer(serializers.Serializer):
    code = serializers.CharField()
    role = serializers.CharField()
    name = serializers.CharField()
    college = serializers.CharField()

    @staticmethod
    def from_user(user: User):
        code = getattr(user, "ecard_code", None) or ""
        role = user.role
        name = user.name
        college = user.college.name if user.college else ""
        return {"code": code, "role": role, "name": name, "college": college}
    
class LoginSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    password = serializers.CharField(max_length=68, write_only=True)
    username = serializers.CharField(max_length=255)
    name=serializers.CharField(max_length=255,read_only=True)
    access_token=serializers.CharField(max_length=255,read_only=True)
    refresh_token=serializers.CharField(max_length=255,read_only=True)

    class Meta:
        model = User
        fields = ['password', 'username', 'name', 'access_token', 'refresh_token', 'id']


    def validate(self,attrs):
        username = attrs.get('username')
        password = attrs.get('password')
        request = self.context.get('request')
        errors = {}

        user = User.login_with_credentials(username=username, password=password, request=request)
        if not user:
            errors['username'] = 'Invalid credentials, try again'

        if user and user.role == User.ROLE_ADMIN and not user.is_email_verified:
            errors['username'] = 'Admin email not verified'

        if errors:
            raise serializers.ValidationError(errors)

        user_tokens = user.tokens()
        return {
            'id': user.id,
            'name': user.name,
            'username': user.username,
            'role': user.role,
            'access_token': str(user_tokens.get('access')),
            'refresh_token': str(user_tokens.get('refresh')),
        }
    
class LogoutUserSerializer(serializers.Serializer):
    refresh_token=serializers.CharField()

    default_error_messages={
        'bad_token':('token is invalid or has expired')
    }

    def validate(self,attrs):
        self.token = attrs.get('refresh_token')
        return attrs
    
    def save(self,**kwargs):
        try:
            token = RefreshToken(self.token)
            token.blacklist()
          
        except TokenError:
            return self.fail('bad_token')

class CollegeSerializer(serializers.ModelSerializer):
    class Meta:
        model = College
        fields = ['id', 'name']


class AdminCreateECardSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=[User.ROLE_STUDENT, User.ROLE_OWNER])
    count = serializers.IntegerField(min_value=1, max_value=50, default=1)
    expires_in_days = serializers.IntegerField(min_value=1, max_value=180, required=False)

    def create(self, validated_data):
        from datetime import timedelta
        import secrets

        user: User = self.context['request'].user
        if user.role != User.ROLE_ADMIN or not user.college:
            raise serializers.ValidationError({'detail': 'Only admins with a college can create cards.'})

        role = validated_data['role']
        count = validated_data.get('count', 1)
        expires_in_days = validated_data.get('expires_in_days')

        expires_at = None
        if expires_in_days:
            expires_at = timezone.now() + timedelta(days=expires_in_days)

        codes = []
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        for _ in range(count):
            # 12-char uppercase alphanumeric code
            code = ''.join(secrets.choice(alphabet) for _ in range(12))
            ECanteenCard.objects.create(
                code=code,
                role=role,
                college=user.college,
                expires_at=expires_at,
            )
            codes.append(code)
        return {'codes': codes}


class ShopSerializer(serializers.ModelSerializer):
    owner_id = serializers.IntegerField(source='owner.id', read_only=True)
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    code = serializers.CharField(read_only=True)
    owner_display_name = serializers.CharField(read_only=True)

    class Meta:
        model = Shop
        fields = ['id', 'code', 'name', 'owner_id', 'owner_username', 'owner_display_name', 'is_active', 'created_at']


class AdminShopCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    owner_name = serializers.CharField(required=False)

    def validate(self, attrs):
        owner_name = attrs.get('owner_name')
        name = attrs.get('name')
        user: User = self.context['request'].user
        errors = {}

        if not user.college:
            errors['detail'] = 'Admin is not associated with any college.'
        if not name or not name.strip():
            errors['name'] = 'Shop name is required.'

        if errors:
            raise serializers.ValidationError(errors)

        attrs['owner_name'] = owner_name
        return attrs

    def create(self, validated_data):
        import secrets
        from .models import ECanteenCard, Shop

        owner_name: str | None = validated_data.get('owner_name')
        name: str = validated_data['name'].strip()
        admin: User = self.context['request'].user

        # Generate a SINGLE uppercase alphanumeric code to use as BOTH:
        # - Shop.code (displayed on the shop card)
        # - Owner ECanteenCard.code (used by owner to sign up)
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        def gen_code(n: int = 12):
            return ''.join(secrets.choice(alphabet) for _ in range(n))

        unified_code = gen_code(12)

        # Create an owner e-card for later signup using the unified code
        owner_ecard = ECanteenCard.objects.create(
            code=unified_code,
            role=User.ROLE_OWNER,
            college=admin.college,
        )

        # Create the shop with the SAME code and store pending owner card
        shop = Shop.objects.create(
            name=name,
            owner=None,
            college=admin.college,
            code=unified_code,
            pending_owner_ecard_code=unified_code,
            owner_display_name=(owner_name or '').strip() or None,
        )

        payload = ShopSerializer(shop).data
        payload['owner_ecard_code'] = unified_code
        return payload


class MenuItemSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)

    class Meta:
        model = MenuItem
        fields = [
            'id', 'name', 'price', 'image_url', 'is_active', 'created_at', 'updated_at'
        ]


class OrderItemSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)

    class Meta:
        model = OrderItem
        fields = ['id', 'name', 'price', 'quantity']


class OrderSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    student_name = serializers.CharField(source='student.name', read_only=True)
    shop_name = serializers.CharField(source='shop.name', read_only=True)
    token_code = serializers.CharField(read_only=True)
    token_number = serializers.IntegerField(read_only=True)

    class Meta:
        model = Order
        fields = ['id', 'shop_name', 'student_name', 'status', 'is_paid', 'is_picked', 'token_code', 'token_number', 'total_amount', 'items', 'created_at', 'updated_at']


class PlaceOrderItem(serializers.Serializer):
    menu_item_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class PlaceOrderSerializer(serializers.Serializer):
    shop_code = serializers.CharField(required=False)
    shop_id = serializers.IntegerField(required=False)
    items = PlaceOrderItem(many=True)

    def validate(self, attrs):
        request = self.context['request']
        user: User = request.user
        errors = {}
        if user.role != User.ROLE_STUDENT:
            errors['detail'] = 'Only students can place orders.'
        if not attrs.get('shop_code') and not attrs.get('shop_id'):
            errors['shop'] = 'Provide shop_code or shop_id.'
        if not attrs.get('items'):
            errors['items'] = 'No items provided.'
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def create(self, validated_data):
        from django.db import transaction
        from decimal import Decimal
        from django.utils import timezone
        request = self.context['request']
        student: User = request.user
        shop = None
        if validated_data.get('shop_id'):
            shop = Shop.objects.get(id=validated_data['shop_id'], college=student.college)
        else:
            shop = Shop.objects.get(code=validated_data['shop_code'], college=student.college)
        with transaction.atomic():
            order = Order.objects.create(shop=shop, student=student, status=Order.STATUS_PENDING, total_amount=Decimal('0.00'))
            total = Decimal('0.00')
            for it in validated_data['items']:
                mi = MenuItem.objects.get(id=it['menu_item_id'], shop=shop, is_active=True)
                qty = int(it['quantity'])
                oi = OrderItem.objects.create(order=order, menu_item=mi, name=mi.name, price=mi.price, quantity=qty)
                total += oi.line_total()
            # Assign per-shop daily token
            today = timezone.localdate()
            last = Order.objects.filter(shop=shop, created_at__date=today).order_by('-token_number').first()
            next_num = (last.token_number if last else 0) + 1
            order.token_number = next_num
            order.token_code = f"TK{next_num:03d}"
            order.total_amount = total
            order.save(update_fields=['total_amount', 'token_number', 'token_code', 'updated_at'])
            return order
