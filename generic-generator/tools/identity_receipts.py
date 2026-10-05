"""Independent qualification of explicit multi-identity HTTP programs."""
import copy


class IdentityMismatch(ValueError):
    pass


def values(node,path):
    current=[node]
    if not path:return current
    for part in path.split('.'):
        array=part.endswith('[]');name=part.removesuffix('[]');next_values=[]
        for item in current:
            if isinstance(item,list) and part.isdigit():
                if int(part)<len(item):next_values.append(item[int(part)])
                continue
            if not isinstance(item,dict) or name not in item:continue
            v=item[name]
            if array:
                if isinstance(v,list):next_values.extend(v)
            else:next_values.append(v)
        current=next_values
    return current


def validate_identity_receipts(receipt,plan):
    cfg=plan.get('identity_program')
    if not cfg:return
    evidence=receipt.get('identity_program',{});obs=evidence.get('observations',{});order=evidence.get('order',[])
    steps={s['id']:s for s in cfg['steps']}
    if set(obs)!=set(steps) or len(order)!=len(steps) or set(order)!=set(steps):raise ValueError('Incomplete multi-identity evidence.')
    done=set()
    for step_id in order:
        task=next(t for t in plan['tasks'] if t['id']==step_id)
        if not set(task['after']).issubset(done):raise ValueError('Identity evidence violates task dependencies.')
        done.add(step_id)
    if any(r.get('code')==401 for r in obs.values()):raise ValueError('Authentication failure in a multi-identity observation; not a qualified scope defect.')
    issues=[]
    for step_id,s in steps.items():
        r=obs[step_id]
        if r.get('actor')!=s['actor'] or r.get('operation')!=s['operation']:raise ValueError('Misattributed actor/operation in evidence.')
        if r.get('code') not in s['expected_codes']:
            issues.append({'step':step_id,'kind':'HTTP_POLICY_MISMATCH','expected':s['expected_codes'],'observed':r.get('code')})
    def operand(v):
        if isinstance(v,dict) and set(v)=={'namespace'}:return [evidence['namespace']+v['namespace']]
        if isinstance(v,dict) and set(v)=={'response'}:
            step,path=v['response'];found=values(obs[step]['body'],path)
            if not found:raise ValueError('Missing oracle value: '+step+'.'+path)
            return found
        return [v]
    for check in cfg['checks']:
        op=check['operator']
        try:left=operand(check['left']);right=operand(check['right'])
        except ValueError as e:
            issues.append({'check':check['id'],'kind':'MISSING_READBACK','error':str(e)})
            continue
        ok=(left==right if op=='equal' else left!=right if op=='not_equal' else all(x in right for x in left) if op=='subset' else None)
        if ok is None:raise ValueError('Unknown qualification operator.')
        if not ok:issues.append({'check':check['id'],'kind':'STATE_POLICY_MISMATCH','expected':right,'observed':left})
    if issues:raise IdentityMismatch(str(issues))
    return {'status':'IDENTITY_SCOPE_POLICY_PASS','regular_users':len(cfg['actors'])-1,'response_count':len(obs),'label':cfg['label']}
