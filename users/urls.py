from django.urls import path
from .views import (
    RegisterUserView,
    VerifyUserEmail,
    LoginUserView,
    LogoutUserView,
    CollegeListView,
    AdminCreateECardView,
    MyCardView,
    AdminShopListCreateView,
    AdminShopDeleteView,
    OwnerMyShopView,
    CollegeShopsListView,
    OwnerMenuListCreateView,
    OwnerMenuItemDetailView,
    ShopMenuPublicView,
    StudentOrdersView,
    OwnerOrdersView,
    OwnerOrderDetailView,
    StudentOrderCancelView,
    RegisterDeviceTokenView,
    GlobalSearchView,
    OwnerUploadImageView,
)

urlpatterns = [
    path('signup/', RegisterUserView.as_view(), name='signup'),
    path('verify-email/', VerifyUserEmail.as_view(), name='verify-email'),
    path('login/', LoginUserView.as_view(), name='login'),
    path('logout/', LogoutUserView.as_view(), name='logout'),
    path('colleges/', CollegeListView.as_view(), name='colleges'),
    path('ecards/', AdminCreateECardView.as_view(), name='create-ecards'),
    path('my-card/', MyCardView.as_view(), name='my-card'),
    # Admin shop management
    path('shops/', AdminShopListCreateView.as_view(), name='shops-list-create'),
    path('shops/<int:pk>/', AdminShopDeleteView.as_view(), name='shops-delete'),
    # Owner self endpoints
    path('shops/me/', OwnerMyShopView.as_view(), name='shop-me'),
    # Student/any authenticated user: list shops in own college
    path('shops/college/', CollegeShopsListView.as_view(), name='shops-by-college'),
    # Owner menu management
    path('menu/', OwnerMenuListCreateView.as_view(), name='owner-menu-list-create'),
    path('menu/<int:item_id>/', OwnerMenuItemDetailView.as_view(), name='owner-menu-item-detail'),
    path('menu/upload-image/', OwnerUploadImageView.as_view(), name='owner-upload-image'),
    # Public (authenticated) shop menu by code or name
    path('shop-menu/', ShopMenuPublicView.as_view(), name='shop-menu'),
    path('search/', GlobalSearchView.as_view(), name='global-search'),
    # Orders and notifications
    path('orders/', StudentOrdersView.as_view(), name='student-orders'),
    path('orders/owner/', OwnerOrdersView.as_view(), name='owner-orders'),
    path('orders/owner/<int:order_id>/', OwnerOrderDetailView.as_view(), name='owner-order-detail'),
    path('orders/<int:order_id>/cancel/', StudentOrderCancelView.as_view(), name='student-order-cancel'),
    path('device-token/', RegisterDeviceTokenView.as_view(), name='register-device-token'),
]
