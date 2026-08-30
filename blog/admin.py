from django.contrib import admin
from .models import Post, Comment, Contact, StockHolding, StockQuoteSnapshot, StockQuoteHistory, PortfolioSnapshot


class PostAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'author', 'date_posted')
    list_display_links = ('id', 'title')
    list_filter = ('author', 'date_posted')
    search_fields = ('title', 'content', 'author')
    list_per_page = 20


admin.site.register(Post, PostAdmin)


class CommentAdmin(admin.ModelAdmin):
    list_display = ('id', 'author', 'post',
                    'approved_comment', 'created_date')
    list_display_links = ('id', 'author', 'post')
    list_filter = ('author', 'created_date')
    list_editable = ('approved_comment', )
    search_fields = ('author', 'post')
    list_per_page = 20

class ContactAdmin(admin.ModelAdmin):
    list_display = ["name", "date_posted"]

admin.site.register(Comment, CommentAdmin)
admin.site.register(Contact, ContactAdmin)


@admin.register(StockHolding)
class StockHoldingAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'symbol', 'shares', 'average_price', 'cost_currency', 'active', 'updated_at')
    list_filter = ('active', 'cost_currency')
    search_fields = ('name', 'ticker', 'symbol')


@admin.register(StockQuoteSnapshot)
class StockQuoteSnapshotAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'symbol', 'price', 'currency', 'source', 'updated_at')
    list_filter = ('currency', 'source')
    search_fields = ('ticker', 'symbol')


@admin.register(StockQuoteHistory)
class StockQuoteHistoryAdmin(admin.ModelAdmin):
    list_display = ('quote_date', 'ticker', 'symbol', 'price', 'currency', 'source')
    list_filter = ('quote_date', 'currency', 'source')
    search_fields = ('ticker', 'symbol')


@admin.register(PortfolioSnapshot)
class PortfolioSnapshotAdmin(admin.ModelAdmin):
    list_display = ('snapshot_date', 'cash_chf', 'bitcoin_chf', 'stocks_chf', 'locked', 'updated_at')
    list_filter = ('locked',)
    search_fields = ('snapshot_date', 'notes')
