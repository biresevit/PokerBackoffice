from types import SimpleNamespace
import uuid
import pytest
from backoffice.chat import Chat
from backoffice.validation import Error


@pytest.mark.parametrize('platform,maximum',[('BluffPokerPlatform',300),('EvenBet',2000)])
def test_platform_message_limit_checked_before_outbox(platform,maximum):
    request,entry=str(uuid.uuid4()),str(uuid.uuid4())
    def replay(sql,*args):
        return {'EntryId':entry,'Body':'x'*maximum,'RequestedBy':'test','Provider':'test'}
    store=SimpleNamespace(site=lambda _: {'platform':platform},db=SimpleNamespace(one=replay),
                          ctx=SimpleNamespace(role='operator',subject='test',provider='test'))
    chat=Chat(store)
    body={'request_id':request,'entry_id':entry,'text':'x'*maximum}
    assert chat.send(1006,'uuid-table',body)['accepted']
    for text in ('x'*(maximum+1),'😀'*(maximum//2+1)):
        with pytest.raises(Error) as error:chat.send(1006,'uuid-table',{**body,'text':text})
        assert error.value.status==400 and str(maximum) in error.value.message
