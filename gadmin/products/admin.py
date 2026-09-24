from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join

from gadmin.deals.models import (ClassificationState, DealProduct, Product,
    ProductMatchExample, ProductMatcherVersion)
from gadmin.metrics.admin import amount, quantity_summary
from . import catalog, identity, jobs, learning
from .history import BASES, history
from .training_status import summary as training_summary

from gadmin.categories.taxonomy import GROUPS


def specs(attributes):
    labels={'zero':'제로','lime':'라임','lemon':'레몬','original':'오리지널','black':'블랙','white':'화이트',
            'volume_ml':'ml','weight_g':'g','capacity_ml':'ml','can':'캔','pet':'페트'}
    values=[]
    for size in attributes.get('sizes',[]):
        key,_,value=size.partition(':')
        values.append(amount(value)+labels.get(key,key))
    values.extend(labels.get(value,value) for value in attributes.get('options',[]))
    values.extend(attributes.get('specs',[]))
    if attributes.get('container'):values.append(labels.get(attributes['container'],attributes['container']))
    return ' · '.join(values) or '제목에 규격 표기 없음'


class ProductForm(forms.ModelForm):
    class Meta:
        model=Product
        fields='__all__'

    def clean(self):
        data=super().clean()
        catalog.lock()
        if 'attributes' in data and not isinstance(data['attributes'],dict):
            raise forms.ValidationError('규격·옵션은 JSON 객체로 입력하세요.')
        if not self.instance.pk or self.instance._state.adding:
            key=identity.signature(data)
            if Product.objects.filter(identity_key=key).exists():raise forms.ValidationError('같은 식별 정보의 상품이 있습니다. 기존 상품을 선택하세요.')
            self.instance.identity_key=key
        return data


class ProductCategoryFilter(admin.SimpleListFilter):
    title='표준 대분류'
    parameter_name='product_category'

    def lookups(self,request,model_admin):
        from gadmin.categories.taxonomy import GROUPS
        return [('', '미분류'),*((key,value[0]) for key,value in GROUPS.items())]

    def queryset(self,request,queryset):
        from django.db.models import Q
        from gadmin.categories.taxonomy import GROUPS
        if self.value()=='':return queryset.filter(category='')
        if self.value() in GROUPS:return queryset.filter(Q(category=self.value())|Q(category__startswith=self.value()+'.'))
        return queryset


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form=ProductForm
    list_display=['name','brand','model','specifications','category','verified','history_link']
    search_fields=['name','brand','model']
    list_filter=['verified',ProductCategoryFilter]
    list_per_page=30
    ordering=['-updated_at']
    change_list_template='monitoring/products_list.html'
    fields=['id','name','brand','model','attributes','category','verified','history_link','created_at']
    readonly_fields=['id','history_link','created_at']

    class Media:
        css={'all':['monitoring/categories.css','monitoring/products.css']}

    def get_readonly_fields(self,request,obj=None):
        return self.readonly_fields+(['brand','model','attributes'] if obj else [])

    def get_queryset(self,request):
        return super().get_queryset(request).filter(is_active=True)

    def change_view(self,request,object_id,form_url='',extra_context=None):
        original=get_object_or_404(Product,pk=object_id)
        if not self.has_view_permission(request,original):raise PermissionDenied
        product=catalog.canonical(original)
        if product.pk!=original.pk:
            return redirect(reverse('admin:deals_product_change',args=[product.pk]))
        return super().change_view(request,object_id,form_url,extra_context)

    def has_delete_permission(self,request,obj=None):return False

    @admin.display(description='규격·옵션')
    def specifications(self,obj):return specs(obj.attributes)

    @admin.display(description='가격 이력')
    def history_link(self,obj):
        if obj._state.adding:return '저장 후 조회할 수 있습니다.'
        return format_html('<a href="{}">게시물·가격 이력 보기</a>',reverse('admin:deals_product_history',args=[obj.pk]))

    def get_urls(self):
        return [path('<uuid:object_id>/history/',self.admin_site.admin_view(self.history_view),name='deals_product_history')]+super().get_urls()

    def changelist_view(self,request,extra_context=None):
        states=dict(ClassificationState.objects.filter(key__in=[
            'products:model','products:matcher','products:llm_training']).values_list('key','value'))
        queue=dict(DealProduct.objects.values_list('status').annotate(count=Count('deal_id')))
        return super().changelist_view(request,extra_context={**(extra_context or {}),
            'product_model':states.get('products:model',{}),'product_matcher':states.get('products:matcher',{}),
            'product_queue':queue,'product_training':training_summary(states.get('products:llm_training')),
            'product_refresh_url':request.get_full_path()})

    def history_view(self,request,object_id):
        product=get_object_or_404(Product,pk=object_id)
        if not self.has_view_permission(request,product):raise PermissionDenied
        canonical=catalog.canonical(product)
        if canonical.pk!=product.pk:
            url=reverse('admin:deals_product_history',args=[canonical.pk])
            if request.GET:url+='?'+request.GET.urlencode()
            return redirect(url)
        error=''
        try:data=history(product,request.GET)
        except ValueError as exc:error=str(exc);data=history(product,{})
        data['minimum_label']=amount(data['minimum'])
        for row in data['results']:
            row['quantity_label']=quantity_summary(row)
            row['price_label']=amount((row['price'] or {}).get('amount'))
            row['amount_label']=amount(row['amount'])
            row['has_safe_url']=row['url'].startswith(('http://','https://'))
            row['assignment_url']=reverse('admin:deals_dealproduct_change',args=[row['deal_id']])
        def page_url(page):
            params=request.GET.copy();params['page']=str(page)
            return '?'+params.urlencode()
        context={**self.admin_site.each_context(request),'title':product.name+' · 가격 이력','opts':self.model._meta,
            'product':product,'specifications':specs(product.attributes),'data':data,'bases':BASES.items(),'error':error,
            'currency_choices':sorted(set(data['currencies'])|{data['currency']}),
            'previous_url':page_url(data['page']-1) if data['page']>1 else '',
            'next_url':page_url(data['page']+1) if data['has_next'] else '',
            'change_url':reverse('admin:deals_product_change',args=[product.pk]),
            'list_url':reverse('admin:deals_product_changelist')}
        return TemplateResponse(request,'monitoring/product_history.html',context,status=400 if error else 200)


class AssignmentForm(forms.ModelForm):
    revision=forms.IntegerField(widget=forms.HiddenInput)
    confirm_extraction=forms.BooleanField(required=False,label='이 추출을 LLM 학습 정답으로 저장')
    training_brand=forms.CharField(required=False,max_length=100,label='브랜드')
    training_name=forms.CharField(required=False,max_length=160,label='상품명·제품군')
    training_model=forms.CharField(required=False,max_length=120,label='모델 번호')
    training_variant=forms.CharField(required=False,max_length=160,label='맛·색상 등 옵션')
    training_category=forms.ChoiceField(required=False,label='대분류',choices=[
        ('unknown','확인 안 됨'),*((key,value[0]) for key,value in GROUPS.items())])

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['revision'].initial=self.instance.request_revision
        self.fields['product'].queryset=Product.objects.filter(is_active=True)
        self.fields['product'].help_text='저장하면 현재 제목의 상품 연결을 확정하고 학습 예제로 보관합니다. 빈 값은 연결을 해제합니다.'
        self.fields['confirm_extraction'].help_text='체크한 경우에만 아래 내용을 운영자 확인 정답으로 저장하고 다음 LoRA 학습에 포함합니다.'
        if not self.is_bound:
            extraction=self.instance.extraction or {}
            for field,key in [('training_brand','brand'),('training_name','name'),
                              ('training_model','model'),('training_variant','variant')]:
                self.initial[field]=extraction.get(key,'')
            self.initial['training_category']=extraction.get('category') or 'unknown'

    class Meta:
        model=DealProduct
        fields=['product','revision','confirm_extraction','training_brand','training_name',
            'training_model','training_variant','training_category']

    def clean(self):
        data=super().clean()
        # Django admin wraps POST in a transaction. Hold this lock through save_model.
        catalog.lock()
        current=DealProduct.objects.select_for_update().get(pk=self.instance.pk)
        if data.get('revision')!=current.request_revision:
            raise forms.ValidationError('게시물 제목 또는 연결이 바뀌었습니다. 새로고침 후 다시 확인하세요.')
        if data.get('confirm_extraction'):
            from .sft import valid_target
            target={
                'brand':data.get('training_brand','').strip(),
                'name':data.get('training_name','').strip(),
                'model':data.get('training_model','').strip(),
                'variant':data.get('training_variant','').strip(),
                'is_product':True,
                'category':data.get('training_category') or 'unknown',
            }
            if not data.get('product'):
                raise forms.ValidationError('LLM 정답을 저장하려면 연결할 상품을 먼저 선택하세요.')
            if not valid_target(current.input_title,target):
                raise forms.ValidationError('브랜드·상품명·모델·옵션을 제목 근거에 맞게 수정한 뒤 저장하세요.')
            data['llm_target']=target
        return data


@admin.register(DealProduct)
class AssignmentAdmin(admin.ModelAdmin):
    form=AssignmentForm
    list_display=['input_title','product','status','source','manual_override','processed_at']
    list_filter=['status','source','manual_override','deal__community_name']
    search_fields=['input_title','product__name']
    list_select_related=['product','deal']
    list_per_page=30
    ordering=['-requested_at']
    autocomplete_fields=['product']
    fieldsets=[
        (None,{'fields':['input_title','product','revision','status','source','manual_override','details','suggestions','reason','processed_at']}),
        ('LLM 학습 정답 (선택)',{'description':'현재 추출값을 제목과 대조해 수정하세요. 체크하지 않으면 상품 연결만 저장합니다.',
            'fields':['confirm_extraction',('training_brand','training_name'),('training_model','training_variant'),'training_category']}),
    ]
    readonly_fields=['input_title','status','source','manual_override','details','suggestions','reason','processed_at']
    actions=['retry']

    class Media:
        css={'all':['monitoring/categories.css','monitoring/products.css']}

    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False

    @admin.display(description='추출 정보')
    def details(self,obj):
        data=obj.extraction
        rows=[(label,data.get(key) or '제목에서 확인 안 됨') for key,label in [('brand','브랜드'),('name','상품명'),('model','모델'),('variant','옵션')]]
        rows.append(('규격',specs(data.get('attributes',{}))))
        return format_html_join('','<div>{}: {}</div>',rows)

    @admin.display(description='학습 모델의 연결 후보')
    def suggestions(self,obj):
        if not obj.candidates:return '비교할 학습 결과 또는 후보가 없습니다.'
        return format_html_join('','<div><a href="{}">{}</a> · 점수 {} · {}</div>',[(
            reverse('admin:deals_product_history',args=[row['id']]),row['name'],row['score'],
            '규격 일치' if row.get('specs_match') else '규격 확인 필요') for row in obj.candidates])

    @admin.display(description='처리 상태 설명')
    def reason(self,obj):
        return {'awaiting_model_capacity':'모델 대기열에 순차적으로 들어갑니다.',
            'model_unavailable':'서버 자원 보호로 모델을 기다리고 있습니다.',
            'not_a_single_product':'제목에서 단일 상품을 특정하지 못했습니다.',
            'brand_or_model_missing':'브랜드 또는 모델 번호가 부족합니다.',
            'identity_not_specific':'다른 상품과 구별할 정보가 부족합니다.',
            'ungrounded_product_fields':'모델 출력이 제목의 실제 표현과 일치하지 않습니다.',
            'mixed_or_ambiguous_package':'서로 다른 규격 또는 선택 상품이 포함되어 있습니다.',
            'product_line_missing':'브랜드 외에 상품을 구별할 이름이 없습니다.',
            'brand_not_specific':'상품 종류나 배송 문구를 브랜드로 인식해 연결을 보류했습니다.',
            'model_not_identifier':'모델 번호와 규격을 구별하지 못해 연결을 보류했습니다.',
            'quantity_in_variant':'묶음 수량을 상품 옵션으로 인식해 연결을 보류했습니다.',
            'quantity_in_product_name':'묶음 수량을 상품명으로 인식해 연결을 보류했습니다.',
            'title_changed_reconfirm':'제목이 변경되었습니다. 상품 연결을 다시 확인하세요.',
            'operator_override':'운영자가 연결을 확인했습니다.'}.get(obj.last_error,obj.last_error or '정상')

    def save_model(self,request,obj,form,change):
        jobs.manual_assign(obj.pk,form.cleaned_data['product'],request.user.get_username(),
            form.cleaned_data['revision'],llm_target=form.cleaned_data.get('llm_target'),
            extraction_reviewed=bool(form.cleaned_data.get('confirm_extraction')))

    @admin.action(description='자동 상품 분석 다시 요청',permissions=['change'])
    def retry(self,request,queryset):
        from django.db.models import F
        from django.utils import timezone
        queryset.update(status='pending',manual_override=False,request_revision=F('request_revision')+1,
            lease_until=None,attempts=0,last_error='',next_attempt_at=timezone.now())
        self.message_user(request,'상품 분석을 다시 요청했습니다.')


@admin.register(ProductMatchExample)
class ExampleAdmin(admin.ModelAdmin):
    list_display=['left_title','right_title','same_product','origin','created_at']
    list_filter=['same_product','origin']
    search_fields=['left_title','right_title']
    list_per_page=30
    fields=['left_title','right_title','same_product','product','origin','actor','created_at']
    readonly_fields=fields
    actions=['train']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False

    @admin.action(description='확인된 전체 예제로 매칭 모델 학습',permissions=['change'])
    def train(self,request,queryset):
        try:version=learning.train_stored()
        except ValueError as exc:self.message_user(request,str(exc),messages.ERROR)
        else:self.message_user(request,'매칭 모델 학습 완료: '+version)


@admin.register(ProductMatcherVersion)
class MatcherAdmin(admin.ModelAdmin):
    list_display=['version','example_count','created_at']
    fields=['version','example_count','metrics','created_at']
    readonly_fields=fields
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False
    def has_change_permission(self,request,obj=None):return False
