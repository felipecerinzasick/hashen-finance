from django.db import models
from django.utils import timezone
from django.urls import reverse
from django.conf import settings
from django.utils.text import slugify
from ckeditor_uploader.fields import RichTextUploadingField


class Resource(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    link = models.URLField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
        

class Contact(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    message = models.TextField()
    date_posted = models.DateTimeField(auto_now_add=True, null=True)

    def __str__(self):
        return self.name


class StockHolding(models.Model):
    CURRENCY_CHOICES = (
        ('CHF', 'CHF'),
        ('USD', 'USD'),
        ('EUR', 'EUR'),
        ('GBP', 'GBP'),
    )

    name = models.CharField(max_length=120)
    ticker = models.CharField(max_length=20)
    symbol = models.CharField(max_length=40)
    shares = models.DecimalField(max_digits=18, decimal_places=8)
    average_price = models.DecimalField(max_digits=18, decimal_places=4)
    cost_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='USD')
    bought_at = models.DateTimeField()
    fallback_value = models.DecimalField(max_digits=18, decimal_places=4, blank=True, null=True)
    fallback_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='USD')
    category = models.CharField(max_length=160, blank=True)
    why_own = models.TextField(blank=True)
    target_price = models.DecimalField(max_digits=18, decimal_places=4, blank=True, null=True)
    target_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='USD')
    target_date = models.DateField(blank=True, null=True)
    target_note = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('ticker', 'bought_at', 'id')

    def __str__(self):
        return '%s %s' % (self.ticker, self.shares)


class MemoNote(models.Model):
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=220, unique=True)
    subtitle = models.CharField(max_length=260, blank=True)
    asset = models.CharField(max_length=120, blank=True)
    horizon = models.CharField(max_length=120, blank=True)
    price_label = models.CharField(max_length=120, blank=True)
    price_value = models.CharField(max_length=80, blank=True)
    position_note = models.TextField()
    exit_note = models.TextField(blank=True)
    thesis = models.TextField(blank=True)
    guardrails = models.TextField(blank=True)
    tags = models.CharField(max_length=260, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at', '-id')

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:210]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
        

class PostManager(models.Manager):
    def like_toggle(self, user, post_obj):
        if user in post_obj.liked.all():
            is_liked = False
            post_obj.liked.remove(user)
        else:
            is_liked = True
            post_obj.liked.add(user)
        return is_liked


class Post(models.Model):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    #content = models.TextField()
    content = RichTextUploadingField()
    liked = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name='liked')
    date_posted = models.DateTimeField(default=timezone.now)

    objects = PostManager()

    class Meta:
        ordering = ('-date_posted', )

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('post_detail', kwargs={'pk': self.pk})


class Comment(models.Model):
    post = models.ForeignKey(
        Post, related_name='comments', on_delete=models.CASCADE)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField()
    created_date = models.DateTimeField(default=timezone.now)
    approved_comment = models.BooleanField(default=True)

    def approve(self):
        self.approved_comment = True
        self.save()

    def get_absolute_url(self):
        return reverse("post_list")

    def __str__(self):
        return self.author
