"""Explicit, reviewable cross-repository contracts; matching never uses names alone."""
import json, re
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from .db import digest

class Contract(BaseModel):
    model_config=ConfigDict(extra='forbid')
    protocol:Literal['http','event','database','grpc','package']
    role:Literal['provides','consumes','publishes','subscribes','reads','writes']
    file:str=Field(min_length=1,max_length=300)
    line:int=Field(default=1,ge=1)
    method:str=Field(default='',max_length=12)
    resource:str=Field(min_length=1,max_length=500)
    scope:str=Field(min_length=1,max_length=500)
    environment:str=Field(min_length=1,max_length=80)
    schema_id:str=Field(default='',alias='schema',max_length=300)

    @model_validator(mode='after')
    def valid(self):
        allowed={'http':{'provides','consumes'},'grpc':{'provides','consumes'},'package':{'provides','consumes'},'event':{'publishes','subscribes'},'database':{'reads','writes'}}
        if self.role not in allowed[self.protocol]: raise ValueError('Invalid protocol role')
        if self.protocol=='http':
            self.method=self.method.upper()
            if self.method not in {'GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'} or not self.resource.startswith('/'): raise ValueError('HTTP method and absolute route required')
            parsed=urlsplit(self.scope)
            if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {'','/'} or parsed.query or parsed.fragment: raise ValueError('HTTP scope must be an origin without credentials')
            self.scope=parsed.scheme+'://'+parsed.netloc.lower()
        return self

class Declaration(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:Literal[1]
    service:str=Field(min_length=1,max_length=120)
    owner:str=Field(default='Unassigned',max_length=120)
    contracts:list[Contract]=Field(default_factory=list,max_length=300)

def load(snapshot,unknown):
    path='.impact-contracts.json'
    if path not in snapshot['files']: return None
    try:
        declaration=Declaration.model_validate(json.loads(snapshot['files'][path]))
        for c in declaration.contracts:
            if c.file not in snapshot['files'] or c.line>max(1,len(snapshot['files'][c.file].splitlines())): raise ValueError('Contract points outside captured source')
        return declaration
    except (ValueError,ValidationError):
        unknown.append({'path':path,'reason':'Invalid contract declaration; cross-repository joins withheld'})
        return None

def route_matches(provider,consumer):
    # A literal request can match a server template; the reverse is not proof.
    p=provider.rstrip('/').split('/'); c=consumer.rstrip('/').split('/')
    return len(p)==len(c) and all(a==b or bool(re.fullmatch(r'\{[^/{}]+\}|:[A-Za-z_]\w*',a)) and not any(x in b for x in '{}:') for a,b in zip(p,c))

def join(graph):
    contracts=[n for n in graph['nodes'] if n['kind']=='contract']; edges=[]
    for consumer in contracts:
        c=consumer['contract']
        if c['role'] not in {'consumes','subscribes','reads'}: continue
        providers=[]
        for provider in contracts:
            p=provider['contract']
            if provider.get('source_validation')=='SOURCE_CONTRADICTION': continue
            if provider['repository_id']==consumer['repository_id'] or p['role'] not in {'provides','publishes','writes'}: continue
            if (p['protocol'],p['scope'],p['environment'])!=(c['protocol'],c['scope'],c['environment']): continue
            if p['protocol']=='http': matched=p['method']==c['method'] and route_matches(p['resource'],c['resource'])
            else: matched=p['resource']==c['resource']
            if matched: providers.append(provider)
        if len(providers)!=1:
            graph['unknown'].append({'path':consumer['path'],'repository_id':consumer['repository_id'],'reason':('Ambiguous' if providers else 'Unresolved')+' '+c['protocol']+' consumer: '+c['resource'],'candidate_ids':[p['id'] for p in providers]})
            continue
        provider=providers[0]; p=provider['contract']
        edges.append({'source':provider['id'],'target':consumer['id'],'kind':'CROSS_REPO_'+c['protocol'].upper(),'evidence':provider['evidence']+consumer['evidence'],'basis':'Exact scoped contract declaration join; source association is owner-declared, not runtime proof','resolution':'DECLARED_MATCH','direction':'provider change → consumer','cross_repository':True})
        if p['schema'] and c['schema'] and p['schema']!=c['schema']:
            graph['unknown'].append({'path':consumer['path'],'repository_id':consumer['repository_id'],'reason':'Contract joined but schema identities differ; compatibility unverified: '+p['schema']+' / '+c['schema']})
    graph['edges']+=edges
    return edges
