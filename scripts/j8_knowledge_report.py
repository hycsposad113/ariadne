"""Offline review report and coverage matrix; never approves or activates knowledge."""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path
import subprocess
from urban_design.knowledge import load_knowledge

ROOT=Path(__file__).resolve().parents[1]

def main():
    k=load_knowledge(ROOT)
    output=ROOT/'artifacts/j8-knowledge-verify'
    decisions=json.loads((output/'review-decisions.json').read_text())
    # S1 collects scope/data; diagnosis belongs to S2. S5 recalculates graphs only.
    relevant={
        'S1':{'land_use','policy'},
        'S2':{'space_syntax','morphology','mobility','public_space','context_response','land_use','policy','portfolio'},
        'S3':{'space_syntax','morphology','mobility','public_space','context_response','land_use','policy','portfolio'},
        'S4':{'space_syntax','morphology','mobility','public_space','portfolio'},
        'S5':{'space_syntax','mobility'},
        'S6':{'space_syntax','morphology','mobility','public_space','context_response','land_use','policy','portfolio'},
        'S7':{c.domain for c in k.cards}, 'S8':{c.domain for c in k.cards},
    }
    domains=sorted({c.domain for c in k.cards}); stages={}
    for stage in (f'S{i}' for i in range(1,9)):
        cells={}
        for domain in domains:
            ids=sorted(c.id for c in k.cards_for(stage,domain))
            reason=None if ids else ('S1 只蒐集範圍及資料，設計與環境解讀從 S2 開始。' if stage=='S1' else 'S5 僅重算已凍結的分模式路網；用途與形態決定由 S3／S6 及 S7 檢查。' if stage=='S5' else 'S4 執行已確認策略及條件的路網生成；介面與政策由 S2／S3 提供，S7 重新審查。')
            cells[domain]={'relevant':domain in relevant[stage], 'card_ids':ids,'reason_zh':reason}
        stages[stage]=cells
    matrix={'version':'0.2.0','status':'PENDING_FOUNDER_REVIEW','relevance_basis_zh':'依 S1 蒐集、S2 診斷、S3 策略、S4 路網、S5 圖重算、S6 量體、S7 驗證、S8 說明職責標定；N/A 不是已有工具實作或通過驗收。','stages':stages}
    (ROOT/'knowledge/coverage-matrix.json').write_text(json.dumps(matrix,ensure_ascii=False,indent=2)+'\n')
    entries=list(k.library.values()); verified=[e for e in entries if e.verification.status=='VERIFIED']
    stats={'cards':len(k.cards),'library':len(entries),'library_verification':dict(Counter(e.verification.status for e in entries)), 'source_query_outcomes':dict(Counter(d['status'] for d in decisions['decisions'])), 'domain_cards':dict(Counter(c.domain for c in k.cards)), 'portfolio_share':sum(c.domain=='portfolio' for c in k.cards)/len(k.cards),'authors':k.author_statistics(),'traditions':dict(Counter(e.tradition for e in verified)), 'regions':dict(Counter(r for e in verified for r in set(e.region))), 'decades':dict(Counter(str(e.year//10*10)+'s' for e in verified)), 'claim_strengths':dict(Counter(c.strength for e in verified for c in e.claims)), 'card_strengths':dict(Counter(c.evidence_strength for c in k.cards)), 'assumptions':sum(p.provenance=='ASSUMED_COMMANDER' for c in k.cards for p in c.parameters),'empty_parameters':sum(not c.parameters for c in k.cards), 'claim_assessment':dict(Counter(c.assessment_basis for e in entries for c in e.claims))}
    families = {
        '規劃、公平與知識批評': ['FANSTEIN10','ROY05','WATSON09','CAMPBELL96','HEALEY97','SCHWANEN18'],
        '形態、類型與密度': ['CONZEN60','CANIGGIA','MOUDON97','MARSHALL05','BRAZIL14','DOVEY14','YE14','CORBUSIER','SPACEMATRIX10'],
        '空間語法、延伸與內部批評': ['HILLIER84','HILLIER93','RATTI04','HILLIERPENN04','MARCUS10','SHARMIN17'],
        '空間網路科學與行動資料': ['PORTA06','BARTHELEMY11','SEVTSUK10'],
        '交通、可及性與自行車': ['EWING10','PUCHER08','CROW','TON19','BUEHLER16','SCHEPERS14','CERVERO97','GEURS04','ELGENEIDY14','IACONO10','BERTOLINI99','NAESS12','HANDY02','FORSYTH15'],
        '公共生活、認知與管理批評': ['AJACOBS93','ALEX77','GEHL10','JACOBS61','LYNCH60','WHYTE80','CARMONA10','LOW05','TALEN99'],
        '高密度環境、住宅生活與韌性': ['NG10','NG09','YUE05','AHERN11','BROWN09','DAVOUDI12'],
        '開放建築、再利用與循環': ['DOUGLAS06','HABRAKEN98','KIRCHHERR17'],
        '土地使用介面與空間公平': ['AZI23','BOGOTA17'],
        '港城與水岸轉型': ['HOYLE00','DESFOR11'],
    }
    mapped = {sid:name for name,ids in families.items() for sid in ids}
    stats['research_families'] = dict(Counter(mapped.get(e.id,'未分組') for e in verified))
    stats['research_family_members'] = families
    (output/'statistics.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2)+'\n')
    before=json.loads((output/'j7-baseline-statistics.json').read_text())
    t=subprocess.check_output(['date','-u','+%Y-%m-%dT%H:%M:%SZ'],text=True).strip()
    text=['# J8 設計知識審核表（候選 0.2.0）','',f'生成時間：{t}。執行者 OpenAI，指揮官 Claude；Founder 尚未審核或鎖版。','',
          f'目前 {len(k.cards)} 張卡、{len(entries)} 筆文獻。新增 25 張；8 份技能只讀本機 knowledge。Loader 不呼叫網路、不啟用約束、不建立 HumanDecision。', '',
          '書目 VERIFIED 只表示 API 的書名、作者及年份核對；ABSTRACT_REVIEW 表示另確認可得摘要。BIBLIOGRAPHIC_SCOPE_ONLY 的主張是保守概念摘要，未逐頁核驗。引用提供概念或反方視角，不證明試算尺寸、M4H 因果、施工或法規。', '',
          '## 查證結果','',f"文獻庫：{stats['library_verification']}。最終查詢項目：{stats['source_query_outcomes']}。NOT_FOUND 未建造假 DOI／ISBN，因此不放入 library。",'',
          'Spacematrix 2010：第一作者與共同作者／版次未完整對上。Transforming Urban Waterfronts：2010／2011 及編者資訊不足。這兩筆保留 AMBIGUOUS，僅候選卡可讀，任何硬性卡均禁止引用。','',
          '年份更正：Marshall 2004、Ng 高密度專書 2009、Caniggia 2001、Le Corbusier 英譯 1929、CROW 採 2016 版；El-Geneidy 2013、Buehler／Dill 2015、Dovey／Pafka 2013 採已查得線上出版年，Yuen 新加坡研究 2006、Barthélemy 網路綜述使用 OpenAlex 2010 紀錄。原 id 保留以維持引用。','',
          '| 移除書目 id | 原因與保留方式 |','|---|---|']
    text += [f'| {sid} | {note} |' for sid,note in decisions['removed'].items()]
    text += ['', 'Founder 與 portfolio 改存 `knowledge/local-context.json`；portfolio 的原設計意圖與數值保留，沒有將其冒充獨立學術來源。Krier 改以 Conzen 比較形態；M4H 卡只保留待取得政策的缺口，不宣稱土地使用合法。','', '## 來源偏誤檢查','',
            f"J7：68 卡，portfolio 18／68（{before['portfolio_share']:.2%}），Founder／作品集 {before['founder_card_source_occurrences']} 次來源引用，所有 {before['sources']} 筆書目未查證。J8：portfolio 18／93（{stats['portfolio_share']:.2%}），Founder 在文獻來源及作者統計為 0。",'',
            f"作者採完整計數：每個作者每筆文獻或卡片引用各計一次；共同作者百分比總和可以超過 100%。不能用合著人數稀釋集中度。作品集脈絡不進入研究分母；58 筆 VERIFIED 文獻及 {stats['authors']['citation_denominator']} 次 VERIFIED 卡片引用分開統計。",'',
            '| 引用最多前 5 作者 | J7 引用數／占比 | J8 引用數／占比 |','|---|---|---|']
    for row in stats['authors']['citations'][:5]:
        b=before['authors_citation'].get(row['author'],{'count':0,'share':0})
        text.append(f"| {row['author']} | {b['count']}／{b['share']:.2%} | {row['count']}／{row['share']:.2%} |")
    text += ['', f"J7 最高：{before['top_author']}（{before['top_author'][0][1]/before['citation_denominator']:.2%}）；J8 引用最高 {stats['authors']['citations'][0]['share']:.2%}；文獻庫作者最高 {stats['authors']['catalogue'][0]['share']:.2%}。兩種分母都低於單一作者 10%，不代表地域或學派已完全平衡。",'']
    for title,key in [('學派','traditions'),('地域（多地域每項各計一筆）','regions'),('年代','decades'),('文獻主張強度','claim_strengths'),('規則卡強度','card_strengths')]:
        text += [f'### {title}','', '| 分類 | 筆數 |','|---|---|']+[f'| {a} | {n} |' for a,n in sorted(stats[key].items(),key=lambda x:-x[1])]+['']
    text += ['### 較廣研究取向分組（審核用）', '', '為避免細小學派標籤掩蓋集中度，再把原 library 標籤作較廣分組；這是公開的審核分析分類，不改 runtime domain 或預設偏好。每筆只計一次，成員清單見 statistics.json。', '', '| 研究取向 | VERIFIED 文獻數 | 占 58 筆比例 |', '|---|---|---|']
    text += [f'| {name} | {n} | {n/len(verified):.2%} |' for name,n in sorted(stats['research_families'].items(),key=lambda item:-item[1])]
    text += ['', '最大的研究取向仍值得 Founder 審查；這不是已證明知識無偏誤。批評與替代方法需要在方案說明中實際並列，不能只以來源數量宣称平衡。', '']
    text += ['### J7／J8 學派與地域前後對照', '', 'J7 使用原稿的一筆来源一票分類，J8 使用 VERIFIED 文獻分類；地域允許多標籤。分類改善與來源增加不表示兩分母直接等價。', '', '| J7 学派 | 来源數 |', '|---|---|']
    text += [f'| {name} | {n} |' for name,n in sorted(before['traditions'].items(), key=lambda item:-item[1])]
    text += ['', '| J7 作者前 5 | 引用數／占比 |', '|---|---|']
    text += [f"| {name} | {row['count']}／{row['share']:.2%} |" for name,row in sorted(before['authors_citation'].items(),key=lambda pair:-pair[1]['count'])[:5]]
    text += ['', f"J7 年代分布：{before['decades']}；J8 年代分布：{stats['decades']}。", '']
    text += ['', '| J7 地域 | 來源數 |', '|---|---|']
    text += [f'| {name} | {n} |' for name,n in sorted(before['regions'].items(), key=lambda item:-item[1])]
    text += ['', f"J7 卡片強度：{before['strengths']}；J8 卡片強度：{stats['card_strengths']}。J7 空參數 {before['empty_parameters']}／68，J8 0／93。", '']
    text += ['仍不足：西歐／北美經典仍是形態與公共生活的較多來源；亞洲增加香港／新加坡，南方增加巴西／哥倫比亞／奈及利亞及非正式都市化，但沒有地方居民訪談，也缺東亞更多城市及非洲不同工業類型的實證。M4H 現行政策、官方用途與手冊條文不能從書目 API 補齊。每領域已列替代文獻，仍需指揮官審查其與卡片的實際支持關係。','',
             '## 覆蓋矩陣摘要','', '| 階段 | '+' | '.join(domains)+' |','|---|'+'---|'*len(domains)]
    for stage,cells in stages.items():text.append('| '+stage+' | '+' | '.join(str(len(cells[d]['card_ids'])) if cells[d]['card_ids'] else 'N/A（見理由）' for d in domains)+' |')
    text += ['', '矩陣每格包含 card_ids、relevant 及空格理由。相關格有卡不代表工具已實作；所有 check 仍是 SPECIFICATION_ONLY。S1 不做設計診斷，S5 不重新決定量體或政策。','',
            '## Founder 待確認的 ASSUMED 值','',f"共 {stats['assumptions']} 個 ASSUMED_COMMANDER 參數；空參數卡 {stats['empty_parameters']} 張。這些值只是候選試算，不曾寫入正式約束。40 m、20 m、Syntax 半徑等既有專案值另標 FOUNDER，作用仍由已接受狀態解析。",'',
            '| 卡 | 參數 | 值／範圍 | 單位 | 理由 |','|---|---|---|---|---|']
    for c in k.cards:
        for p in c.parameters:
            if p.provenance=='ASSUMED_COMMANDER':text.append(f'| {c.id} | {p.name} | {p.value if p.value is not None else list(p.range)} | {p.unit} | {p.rationale_zh} |')
    text+=['','## 每張卡的白話審核','', '需判斷：規則是否合適、不同回應的代價是否完整、數值是否值得试算。證據不是投票表；不要因來源多而偏好某一方案。','']
    for c in k.cards:
        text += [f'### {c.id}｜{c.title_zh}','',f'**規則**：{c.statement_zh}',f'**理由**：{c.rationale_zh}',f'**層級／強度／權限**：{c.evidence_level}／{c.evidence_strength}／{c.enforcement}／{c.source_count_flag}。', '**參數**：'+'；'.join(f'{p.name}＝{p.value if p.value is not None else list(p.range)} {p.unit}（{p.provenance}／{p.status}）' for p in c.parameters), '**出處**：']
        for ref in c.sources:
            e=k.library[ref.library_id];identifier=e.doi or e.isbn or e.openalex_id
            text.append(f'- {e.id}／{ref.claim_id}：{e.title}；{"、".join(e.authors)}；{e.year}；{identifier}；{e.verification.status}／{e.claims[0].assessment_basis}。{ref.support_scope_zh}')
        if c.local_context_refs:text.append('**本機脈絡（不计研究來源）**：'+', '.join(c.local_context_refs))
        text += ['**可選回應**：']+[f'- {r.action_zh}；代價：{r.tradeoff_zh}' for r in c.design_responses]
        text += [f'**爭議與地域限制**：{c.debates_zh} {c.context_validity_zh}',f'**例外**：{c.exceptions_zh}','']
    text=['\n'.join(text).replace('公开','公開').replace('单一','單一').replace('试算','試算').replace('不计','不計').replace('学派','學派').replace('来源','來源').replace('宣称','宣稱')]
    (ROOT/'docs/design-knowledge/rule-cards-review-20261008-zh.md').write_text(text[0].rstrip()+'\n')
    print(json.dumps({key:stats[key] for key in ('cards','library','library_verification','source_query_outcomes','assumptions','empty_parameters')},ensure_ascii=False))

if __name__=='__main__':main()
