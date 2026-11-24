import test from 'node:test'
import assert from 'node:assert/strict'
import { consumeChatStream, streamChat } from '../chatStream.js'
const encoder = new TextEncoder()
function response(text, oneByte = false) {
 const bytes = encoder.encode(text)
 return new Response(new ReadableStream({ start(controller) { if (oneByte) for(const byte of bytes) controller.enqueue(Uint8Array.of(byte)); else controller.enqueue(bytes); controller.close() } }), {headers:{'Content-Type':'text/event-stream'}})
}
test('public event dicts survive split UTF8, split CRLF, multiline data and EOF result without newline', async () => {
 const events = []
 const text = ': keep-alive\r\n\r\nevent: progress\r\ndata: {"type":"agent",\r\ndata: "status":"completed","label":"नेपाल"}\r\n\r\nevent: result\r\ndata: {"message":"नतिजा"}'
 const result = await consumeChatStream(response(text,true), {onEvent:event=>events.push(event)})
 assert.deepEqual(events,[{type:'agent',status:'completed',label:'नेपाल'}])
 assert.equal(result.message,'नतिजा')
})
test('in-stream errors retain actual status and early connection closes fail', async () => {
 await assert.rejects(consumeChatStream(response('event: error\ndata: {"message":"Provider unavailable","status":503}\n\n')),error=>error.message==='Provider unavailable' && error.status===503)
 await assert.rejects(consumeChatStream(response('event: progress\ndata: {"type":"model","status":"working"}\n\n')),/closed before an answer/)
})
test('malformed and oversized frames are bounded rather than silently accepted', async () => {
 await assert.rejects(consumeChatStream(response('event: result\ndata: {bad}\n\n')),/invalid stream data/)
 await assert.rejects(consumeChatStream(response('event: progress\ndata: '+ 'x'.repeat(100)),{maxFrameBytes:50}),/stream size limit/)
})
test('abort stops waiting and cancels the reader without claiming provider cancellation', async () => {
 const controller = new AbortController()
 let canceled = false
 const source = new Response(new ReadableStream({start(stream){stream.enqueue(encoder.encode('event: progress\ndata: {"type":"model","status":"working"}\n\n'))},cancel(){canceled=true}}))
 await assert.rejects(consumeChatStream(source,{signal:controller.signal,onEvent(){controller.abort()}}),error=>error.name==='AbortError')
 assert.equal(canceled,true)
})
test('only a pre-execution HTTP403 refreshes the session; in-stream model errors are never replayed', async () => {
 const originalFetch = globalThis.fetch, originalLocation = globalThis.location, originalStorage = globalThis.sessionStorage
 let savedToken = 'expired', streamRequests = 0, bootstraps = 0
 globalThis.location={hash:''}
 globalThis.sessionStorage={getItem:()=>savedToken,setItem:(key,value)=>{savedToken=value}}
 globalThis.fetch=async(path,options)=>{
  if(path==='/api/workspace/session'){bootstraps++;return Response.json({success:true,data:{token:'fresh'}})}
  assert.equal(path,'/api/workspace/chat/stream');streamRequests++
  if(streamRequests===1)return Response.json({success:false,error:'Expired'},{status:403})
  assert.equal(options.headers['X-Setup-Token'],'fresh')
  return response('event: error\ndata: {"message":"Upstream failed","status":403}\n\n')
 }
 try { await assert.rejects(streamChat({messages:[{role:'user',content:'Hello'}]}),error=>error.message==='Upstream failed'&&error.status===403);assert.equal(streamRequests,2);assert.equal(bootstraps,1) }
 finally{globalThis.fetch=originalFetch;globalThis.location=originalLocation;globalThis.sessionStorage=originalStorage}
})
