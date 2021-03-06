# -*- coding: utf-8 -*-
"""
Created on Thu Nov 23 21:53:32 2017

@author: gason
"""

import pandas as pd
import numpy as np
import re
import time
import os
from collections import Iterable

from pandas.api.types import is_string_dtype
from pandas.api.types import is_numeric_dtype
from pandas.api.types import is_number
from pandas.api.types import is_datetime64_any_dtype
from pandas.api.types import is_categorical_dtype
from scipy import stats

from . import report as _rpt
from . import config
from .report import genwordcloud

from .utils import iqr

#from sklearn.neighbors import KernelDensity
import matplotlib.pyplot as plt
import seaborn as sns

_thisdir = os.path.split(__file__)[0]
# default chinese font
from matplotlib.font_manager import FontProperties
font_path=config.font_path
if font_path:
    myfont=FontProperties(fname=font_path)
    sns.set(font=myfont.get_name())



def _freedman_diaconis_bins(a):
    """Calculate number of hist bins using Freedman-Diaconis rule."""
    # From http://stats.stackexchange.com/questions/798/
    a = np.asarray(a)
    h = 2 * iqr(a) / (len(a) ** (1 / 3))
    # fall back to sqrt(a) bins if iqr is 0
    if h == 0:
        return int(np.sqrt(a.size))
    else:
        return int(np.ceil((a.max() - a.min()) / h))



def distributions(a,hist=True,bins=None,norm_hist=True,kde=True,grid=None,gridsize=100,clip=None):
    '''数组的分布信息
    hist=True,则返回分布直方图(counts,bins)
    kde=True,则返回核密度估计数组(grid,y)

    example
    -------
    a=np.random.randint(1,50,size=(1000,1))
    '''
    a = np.asarray(a).squeeze()
    if hist:
        if bins is None:
            bins = min(_freedman_diaconis_bins(a), 50)
        counts,bins=np.histogram(a,bins=bins)
        if norm_hist:
            counts=counts/counts.sum()
    if kde:
        bw='scott'
        cut=3
        if clip is None:
            clip = (-np.inf, np.inf)
        try:
            kdemodel = stats.gaussian_kde(a, bw_method=bw)
        except TypeError:
            kdemodel = stats.gaussian_kde(a)
        bw = "scotts" if bw == "scott" else bw
        bw = getattr(kdemodel, "%s_factor" % bw)() * np.std(a)
        if grid is None:
            support_min = max(a.min() - bw * cut, clip[0])
            support_max = min(a.max() + bw * cut, clip[1])
            grid=np.linspace(support_min, support_max, gridsize)
        y = kdemodel(grid)
    if hist and not(kde):
        return counts,bins
    elif not(hist) and kde:
        return grid,y
    elif hist and kde:
        return ((counts,bins),(grid,y))
    else:
        return None


def dtype_detection(columns,data=None,category_detection=True,StructureText_detection=True,\
datetime_to_category=True):
    '''检测数据中单个变量的数据类型
    将数据类型分为以下4种
    1. number,数值型
    2. category,因子
    3. datetime,时间类型
    4. text,文本型
    5. text_st,结构性文本，比如ID,
    6. group_number,连续

    parameter
    ---------
    columns: str,列名,也可以直接是Series数据
    data:pd.DataFrame类型
    # 如果有data,则函数会改变原来data的数据类型

    return:
    result:dict{
        'name':列名,
        'vtype':变量类型,
        'ordered':是否是有序因子,
        'categories':所有的因子}

    '''

    if data is None:
        data=pd.DataFrame(columns)
        c=data.columns[0]
    else:
        c=columns

    if not(isinstance(data,pd.core.frame.DataFrame)):
        print('Please ensure the type of data is Series.')
        raise('')

    dtype=data[c].dtype
    name=c
    ordered=False
    categories=[]
    n_sample=data[c].count()
    if is_numeric_dtype(dtype):
        vtype='number'
        ordered=False
        categories=[]
        # 纠正误分的数据类型。如将1.0，2.0，3.0都修正为1，2，3
        if data[c].dropna().astype(np.int64).sum()==data[c].dropna().sum():
            data.loc[data[c].notnull(),c]=data.loc[data[c].notnull(),c].astype(np.int64)
        if category_detection and len(data[c].dropna().unique())<np.sqrt(n_sample) and data[c].value_counts().mean()>=2:
            data[c]=data[c].astype('category')
            ordered=data[c].cat.ordered
            vtype='category'
            categories=list(data[c].dropna().cat.categories)
        result={'name':name,'vtype':vtype,'ordered':ordered,'categories':categories}
    elif is_string_dtype(dtype):
        # 处理时间类型
        tmp=data[c].map(lambda x: np.nan if '%s'%x == 'nan' else len('%s'%x))
        tmp=tmp.dropna().astype(np.int64)       
        if not(any(data[c].dropna().map(is_number))) and 7<tmp.max()<20 and tmp.std()<0.1:
            try:
                data[c]=pd.to_datetime(data[c])
            except :
                pass


        # 处理可能的因子类型
        #时间格式是否处理为True 且
        if datetime_to_category:
            if len(data[c].dropna().unique())<np.sqrt(n_sample):
                data[c]=data[c].astype('category')
        else:
            if not(np.issubdtype(data[c].dtype,np.datetime64)) and len(data[c].dropna().unique())<np.sqrt(n_sample):
                data[c]=data[c].astype('category')

        # 在非因子类型的前提下，将百分数转化成浮点数，例如21.12%-->0.2112
        if is_string_dtype(data[c].dtype) and not(is_categorical_dtype(data[c].dtype)) and all(data[c].str.contains('%')):
            data[c]=data[c].str.strip('%').astype(np.float64)/100

        if is_categorical_dtype(data[c].dtype):
            vtype='category'
            categories=list(data[c].cat.categories)
            ordered=data[c].cat.ordered
        # 时间格式
        elif np.issubdtype(data[c].dtype,np.datetime64):
            vtype='datetime'
        # 是否是结构化数组
        elif StructureText_detection and tmp.dropna().std()==0:
            # 不可迭代，不是字符串
            if not(isinstance(data[c].dropna().iloc[0],Iterable)):
                vtype='text'
            else:
                k=set(list(data[c].dropna().iloc[0]))
                for x in data[c]:
                    if isinstance(x,str) and len(x)>0:
                        k&=set(list(x))
                if len(k)>0:
                    vtype='text_st'
                else:
                    vtype='text'
        elif is_numeric_dtype(data[c].dtype):
            vtype='number'
            ordered=False
            categories=[]
        else:
            vtype='text'
        result={'name':name,'vtype':vtype,'ordered':ordered,'categories':categories}
    elif is_datetime64_any_dtype(dtype):
        vtype='datetime'
        result={'name':name,'vtype':vtype,'ordered':ordered,'categories':categories}
    else:
        print('unknown dtype!')
        result=None

    return result




def type_of_var(data,inplace=True):
    '''返回各个变量的类型
    将数据类型分为以下4种
    1. number,数值型
    2. category,因子
    3. datetime,时间类型
    4. text,文本型
    5. text_st,结构性文本，比如ID,

    parameter
    ---------
    data:pd.DataFrame类型
    inplace: 是否直接更改数据

    return:
    var_type:dict{
        ColumnName:type,}

    '''
    var_type={}
    if not inplace:
        data1=data.loc[:,:]
        for c in data1.columns:
            result=dtype_detection(c,data1,datetime_to_category=False)
            if result is not None:
                var_type[c]=result['vtype']
    else:
        for c in data.columns:
            result=dtype_detection(c,data,datetime_to_category=False)
            if result is not None:
                var_type[c]=result['vtype']
    return var_type



def var_detection(data,combine=True):
    '''检测整个数据的变量类型,内部使用，外部请用type_of_var
    parameter
    ---------
    data: 数据,DataFrame格式
    combine: 检测变量中是否有类似的变量，有的话则会合并。

    return
    ------
    var_list:[{'name':,'vtype':,'vlist':'ordered':,'categories':},]

    '''
    var_list=[]
    for c in data.columns:
        result=dtype_detection(c,data)
        if result is not None:
            var_list.append(result)
    if not(combine):
        return var_list,data
    var_group=[]
    i=0
    pattern=re.compile(r'(.*?)(\d+)')
    while i < len(var_list)-1:
        v=var_list[i]
        vnext=var_list[i+1]
        if v['vtype']!='number' or vnext['vtype']!='number':
            i+=1
            continue
        tmp1=[]
        for vv in var_list[i:]:
            if vv['vtype']!='number':
                break
            w=re.findall(pattern,'%s'%vv['name'])
            if len(w)==0 or (len(w)>0 and len(w[0])<2):
                break
            tmp1.append((w[0][0],w[0][1]))
        if len(tmp1)<2:
            i+=1
            continue
        flag1=len(set([t[0] for t in tmp1]))==1
        flag2=np.diff([int(t[1]) for t in tmp1]).sum()==len(tmp1)-1
        if flag1 and flag2:
            var_group.append(list(range(i,i+len(tmp1))))
            i+=len(tmp1)
    var_group_new={}
    var_group_total=[]#将所有的分组ind加起来
    for vi in var_group:
        var_group_total+=vi
        name='{}-->{}'.format(var_list[vi[0]]['name'],var_list[vi[-1]]['name'])
        vlist=[var_list[v]['name'] for v in vi]
        vtype='group_number'
        tmp={'name':name,'vtype':vtype,'vlist':vlist,'ordered':True,'categories':vlist}
        var_group_new[vi[0]]=tmp
    var_list_new=[]
    var_list_have=[]
    for i,v in enumerate(var_list):
        if i not in var_group_total:
            v['vlist']=[v['name']]
            var_list_new.append(v)
            var_list_have+=v['vlist']
        elif i in var_group_total and v['name'] not in var_list_have:
            var_list_new.append(var_group_new[i])
            var_list_have+=var_group_new[i]['vlist']
    return var_list_new,data

def describe(data):
    '''
    对每个变量生成统计指标特征
    '''
    #var_list=var_detection(data,combine=False)
    result=pd.DataFrame()
    for c in data.columns:
        result=pd.concat([result,data[[c]].describe()],axis=1)

    return result


def plot(data,figure_type='auto',chart_type='auto',vertical=False,ax=None):
    '''auto choose the best chart type to draw the data
    paremeter
    -----------
    figure_type: 'mpl' or 'pptx' or 'html'
    chart_type: 'hist' or 'dist' or 'kde' or 'bar' ......

    return
    -------
    chart:dict format.
    .type: equal to figure_type
    .fig: only return if type == 'mpl'
    .ax:
    .chart_data:

    '''

    # 判别部分

    # 绘制部分
    data=pd.DataFrame(data)
    chart={}
    if figure_type in ['mpl','matplotlib']:
        chart['type']='mpl'
        if ax is None:
            fig,ax=plt.subplots()
        if chart_type in ['hist','kde']:
            for c in data.columns:
                sns.kdeplot(data[c].dropna(),shade=True,ax=ax)
            legend_label=ax.get_legend_handles_labels()
            if len(legend_label)>0 and len(legend_label[0])>0:
                ax.legend()
            ax.axis('auto')
        elif chart_type in ['dist']:
            for c in data.columns:
                sns.distplot(data[c].dropna(),ax=ax)
            legend_label=ax.get_legend_handles_labels()
            if len(legend_label)>0 and len(legend_label[0])>0:
                ax.legend()
            ax.axis('auto')
        elif chart_type in ['scatter']:
            ax.xaxis.set_ticks_position('none')
            ax.yaxis.set_ticks_position('none')
            ax.axhline(y=0, linestyle='-', linewidth=1.2, alpha=0.6)
            ax.axvline(x=0, linestyle='-', linewidth=1.2, alpha=0.6)
            color=['blue','red','green','dark']
            if not isinstance(data,list):
                data=[data]
            for i,dd in enumerate(data):
                if '%s'%dd.iloc[:,0] != 'nan' or '%s'%dd.iloc[:,1] != 'nan':
                    ax.scatter(dd.iloc[:,0], dd.iloc[:,1], c=color[i], s=50,
                               label=dd.columns[1])
                    for _, row in dd.iterrows():
                        ax.annotate(row.name, (row.iloc[0], row.iloc[1]), color=color[i],fontproperties=myfont,fontsize=10)
            ax.axis('equal')
            legend_label=ax.get_legend_handles_labels()
            if len(legend_label)>0 and len(legend_label[0])>0:
                ax.legend()
        try:
            chart['fig']=fig
        except:
            pass
        chart['ax']=ax
        return chart



def AnalysisReport(data,filename=None,var_list=None):
    '''
    直接生成报告
    '''
    if var_list is None:
        var_list,data=var_detection(data)
        #print(var_list)
        #print('============')

    slides_data=[]

    if filename is None:
        filename='AnalysisReport'+time.strftime('_%Y%m%d%H%M', time.localtime())
        p=_rpt.Report()
        p.add_cover(title=os.path.splitext(filename)[0])
    elif isinstance(filename,str):
        p=_rpt.Report()
        p.add_cover(title=os.path.splitext(filename)[0])
    elif isinstance(filename,_rpt.Report):
        p=filename
        filename='AnalysisReport'+time.strftime('_%Y%m%d%H%M', time.localtime())
    else:
        print('reportgen.AnalysisReport::cannot understand the filename')
        return None

    result=describe(data)
    slide_data={'data':result,'slide_type':'table'}
    p.add_slide(data=slide_data,title='数据字段描述')

    for v in var_list:
        vtype=v['vtype']
        name=v['name']
        vlist=v['vlist']
        #print(name,':',vtype)
        if vtype == 'number':
            chart=plot(data[name],figure_type='mpl',chart_type='kde')
            chart['fig'].savefig('kdeplot1.png',dpi=200)
            chart['fig'].clf()
            del chart
            chart=plot(data[name],figure_type='mpl',chart_type='dist')
            chart['fig'].savefig('kdeplot2.png',dpi=200)
            chart['fig'].clf()
            del chart
            summary='''平均数为：{:.2f}，标准差为：{:.2f}，最大为：{}'''\
            .format(data[name].mean(),data[name].std(),data[name].max())
            footnote='注: 样本N={}'.format(data[name].count())
            slide_data=[{'data':'kdeplot1.png','slide_type':'picture'},{'data':'kdeplot2.png','slide_type':'picture'}]
            p.add_slide(data=slide_data,title=name+' 的分析',summary=summary,footnote=footnote)
            slides_data.append(slide_data)
            os.remove('kdeplot1.png')
            os.remove('kdeplot2.png')
        elif vtype == 'category':
            tmp=pd.DataFrame(data[name].value_counts())
            tmp=tmp*100/tmp.sum()#转换成百分数
            if ('ordered' in v) and v['ordered']:
                tmp=pd.DataFrame(tmp,index=v['categories'])
            footnote='注: 样本N={}'.format(data[name].count())
            slide_data={'data':tmp,'slide_type':'chart','type':'COLUMN_CLUSTERED'}
            summary='{}占比最大为: {:.2f}%'.format(tmp.iloc[:,0].argmax(),tmp.iloc[:,0].max())
            p.add_slide(data=slide_data,title=name+' 的分析',summary=summary,footnote=footnote)
            slides_data.append(slide_data)
        elif vtype == 'datetime':
            if data[name].value_counts().max()==1:
                print('the dtype of {} column is datetime, continue...')
                continue
            tmp=pd.DataFrame(data[name].astype('object').value_counts())
            tmp=tmp*100/tmp.sum()#转换成百分数
            tmp=tmp.sort_index()#排序
            if ('ordered' in v) and v['ordered']:
                tmp=pd.DataFrame(tmp,index=v['categories'])
            footnote='注: 样本N={}'.format(data[name].count())
            slide_data={'data':tmp,'slide_type':'chart','type':'COLUMN_CLUSTERED'}
            summary='{}占比最大为: {:.2f}%'.format(tmp.iloc[:,0].argmax(),tmp.iloc[:,0].max())
            p.add_slide(data=slide_data,title=name+' 的分析',summary=summary,footnote=footnote)
            slides_data.append(slide_data)
        elif vtype == 'text':
            try:
                tmp=','.join(data[name].dropna())
                if len(tmp)>1:
                    img=genwordcloud(tmp,font_path=font_path)
                    img.save('tmp.png')
                    footnote='注: 样本N={}'.format(data[name].count())
                    slide_data={'data':'tmp.png','slide_type':'picture'}
                    p.add_slide(data=slide_data,title=name+' 的词云分析',footnote=footnote)
                    slides_data.append(slide_data)
                    os.remove('tmp.png')
            except:
                print('cannot understand : {}'.format(name))
                pass
        elif vtype == 'group_number':
            tmp=pd.DataFrame(data.loc[:,vlist].mean())
            footnote='注: 样本N={}'.format(data.loc[:,vlist].count().max())
            slide_data={'data':tmp,'slide_type':'chart','type':'COLUMN_CLUSTERED'}
            summary='{}占比最大为: {:.2f}%'.format(tmp.iloc[:,0].argmax(),tmp.iloc[:,0].max())
            p.add_slide(data=slide_data,title=name+' 的分析',summary=summary,footnote=footnote)
            slides_data.append(slide_data)
        elif vtype == 'text_st':
            print('The field: {} may be id or need to be designed'.format(name))
        else:
            print('unknown type: {}'.format(name))
    p.save(os.path.splitext(filename)[0]+'.pptx')
    return slides_data
