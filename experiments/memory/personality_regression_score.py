"""Validate every frozen case/label before computing persona comparison metrics."""
def score(data,obs,labels,mapping):
    cases=data['cases'];paired_cases=[c for c in cases if c['cohort']!='regression'];old=[c for c in cases if c['cohort']=='regression']
    def index(rows):
        result={}
        for r in rows:
            if r['case_id'] in result:raise ValueError('Duplicate review label')
            result[r['case_id']]=r
        return result
    paired=index(labels['pairs']);reg=index(labels['regression'])
    if set(paired)!={c['id'] for c in paired_cases} or set(reg)!={c['id'] for c in old}:
        raise ValueError('Missing or extraneous review case')
    if set(mapping)!=set(paired):raise ValueError('Mask-map mismatch')
    raw={}
    for r in obs['rows']:
        key=(r['case_id'],r['arm'])
        if key in raw:raise ValueError('Duplicate raw response')
        raw[key]=r
    expected={(c['id'],a) for c in cases for a in c.get('arms',['baseline','candidate'])}
    if set(raw)!=expected:raise ValueError('Incomplete or unexpected response denominator')
    def check(value):
        if type(value['quality']) is not int or not 0<=value['quality']<=2:raise ValueError('Invalid quality label')
        for k in ['required_pass','format_pass','boundary_failure']:
            if type(value[k]) is not bool:raise ValueError('Invalid boolean label')
        if value['boundary_failure'] and value['required_pass']:raise ValueError('Boundary contradiction')
    arms={'baseline':[],'candidate':[]};wins=losses=ties=0
    for c in paired_cases:
        label=paired[c['id']];m=mapping[c['id']]
        if set(m)!= {'left','right'} or set(m.values())!={'baseline','candidate'}:raise ValueError('Invalid pair map')
        for side in ['left','right']:
            v=label[side];check(v);arms[m[side]].append({'case_id':c['id'],**v})
        pref=label['style_preference']
        if c['style_case']:
            if pref not in ('left','right','tie'):raise ValueError('Missing style preference')
            if pref=='tie':ties+=1
            elif m[pref]=='candidate':wins+=1
            else:losses+=1
        elif pref is not None:raise ValueError('Non-style case contributes a style vote')
    for c in old:check(reg[c['id']]['candidate'])
    def format_ok(id,value):
        text=raw[id,'candidate'].get('reply',{}).get('text','')
        return value['format_pass'] and 0<len(text)<=480
    candidate=arms['candidate'];baseline=arms['baseline']
    metrics={'completed_responses':sum(r.get('reply',{}).get('status')=='completed' and r['reply'].get('usage_settled') is True for r in raw.values()),
      'collection_errors':len(obs['errors']),'candidate_required_passes':sum(r['required_pass'] for r in candidate),
      'candidate_boundary_failures':sum(r['boundary_failure'] for r in candidate),
      'candidate_format_passes':sum(format_ok(r['case_id'],r) for r in candidate),
      'candidate_quality_total':sum(r['quality'] for r in candidate),
      'candidate_quality_delta':sum(r['quality'] for r in candidate)-sum(r['quality'] for r in baseline),
      'candidate_style_wins':wins,'candidate_style_losses':losses,'additional_api_usd':obs['additional_api_usd'],
      'regression_required_passes':sum(r['candidate']['required_pass'] for r in reg.values()),
      'regression_format_passes':sum(format_ok(r['case_id'],r['candidate']) for r in reg.values()),
      'regression_boundary_failures':sum(r['candidate']['boundary_failure'] for r in reg.values())}
    return {'metrics':metrics,'baseline_quality_total':sum(r['quality'] for r in baseline),
      'baseline_required_passes':sum(r['required_pass'] for r in baseline),'candidate_style_ties':ties,'decoded_labels':arms,'regressions':labels['regression']}
