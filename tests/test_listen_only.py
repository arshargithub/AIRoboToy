import asyncio,unittest
from tavi.listen_only import listen_only
from tavi.conversation import Conversation
from tavi.chunked_conversation import ChunkedConversation
from tavi.conversation_providers import Speech,LOCAL_REPLIES
from tavi.storage import Store

POSITIVE=[
'Just listen.','Just listen to me, please.','Please just listen.','Just stay with me for a moment.','I just want someone to listen right now.','I need you to listen.','Can you just listen?','Could you please just listen to me?',
'I feel bad. Just listen.','I am upset, just listen to me.','I still feel bad, but no ideas or advice please. Just stay with me for a moment.','No advice please, just listen.','I do not want any ideas right now. Just listen.','I feel overwhelmed today. I just want you to listen.','I’m upset. Please just listen.','Please no suggestions. Just stay here with me.']
NEGATIVE=[
'What does just listen mean?','She said just listen.','Mira told me to just listen.','If I say just listen, what would you do?','Do not just listen.','Please do not just listen; give me ideas.','I do not want you to just listen.','I want advice, not just listening.','Tell me a story with the words "just listen".','"Just listen"','I feel sad because he said just listen.','Why should I just listen?','Should I just listen?','No advice please, but actually give me ideas.','I feel tense. What might help?','I feel bad; please suggest something.','Would Leon enjoy listening to piano?','I need you to listen to a song and describe it.','Just listen to this song and tell me about it.','Just stay with me for a moment and give me some ideas.','I would rather build a bridge.','Goodbye, Paprika.','Stop talking.','We are playing a game called just listen.']
class ListenIntentTests(unittest.TestCase):
 def test_explicit_supported_forms(self):
  for text in POSITIVE:
   with self.subTest(text=text):self.assertTrue(listen_only(text))
 def test_reports_quotes_negation_and_ordinary_requests_not_claimed(self):
  for text in NEGATIVE:
   with self.subTest(text=text):self.assertFalse(listen_only(text))

class ListenControllerTests(unittest.IsolatedAsyncioTestCase):
 async def exercise(self,cls):
  store=Store();calls=[]
  class Provider:
   async def reply(self,history):calls.append(history);return 'A normal answer.'
   async def stream_reply(self,history):calls.append(history);yield 'A normal answer.'
   async def close(self):pass
  class Voice:
   async def synthesize(self,text):return Speech(text.encode(),100)
  c=cls(store,provider=Provider(),speech=Voice());c.start('test')
  def feed(text,n):c.feed('test',{'events':[{'type':'speech_started','utterance':n},{'type':'recognition','utterance':n,'text':text,'final':True}]})
  async def play():
   async with asyncio.timeout(2):
    while not c.audio:await asyncio.sleep(0)
    while c.audio:
     a=c.audio;body={'response_id':a['id'],'sequence':a.get('sequence',0)};c.command('test','started',body);c.command('test','played',body);await asyncio.sleep(0)
  try:
   feed('Just listen.',1);await asyncio.sleep(0);self.assertEqual(calls,[]);self.assertIsNone(c.audio)
   feed('Paprika, I still feel bad, but no ideas or advice please. Just stay with me for a moment.',2);await play()
   self.assertEqual(c.last_reply,LOCAL_REPLIES['listen']);self.assertEqual(calls,[]);self.assertTrue(c.engaged);self.assertEqual(c.paid_turns,0)
   feed('Could you suggest a project now?',3);await play();self.assertEqual(len(calls),1);self.assertEqual(c.last_reply,'A normal answer.')
  finally:await c.close();store.close()
 async def test_whole_reply_path(self):await self.exercise(Conversation)
 async def test_sentence_reply_path(self):await self.exercise(ChunkedConversation)
