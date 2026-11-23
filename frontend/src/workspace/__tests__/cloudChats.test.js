import test from 'node:test'
import assert from 'node:assert/strict'
import { mergeChats } from '../cloud.js'

test('shared chat merge preserves concurrent messages and latest custom title', () => {
 const remote=[{id:'chat',updated:2,customTitle:'Renamed',messages:[{id:'a',content:'Old'},{id:'b',content:'Teammate'}]}]
 const local=[{id:'chat',updated:3,customTitle:'Renamed again',messages:[{id:'a',content:'Old'},{id:'c',content:'Mine'}]}]
 const [chat]=mergeChats(remote,local)
 assert.equal(chat.customTitle,'Renamed again')
 assert.deepEqual(chat.messages.map(m=>m.id),['a','b','c'])
})
test('shared chat merge never silently discards old chats or long conversations',()=>{
 const chats=Array.from({length:90},(_,i)=>({id:`chat-${i}`,updated:i,messages:Array.from({length:70},(_,j)=>({id:`m-${j}`}))}))
 const merged=mergeChats([],chats)
 assert.equal(merged.length,90)
 assert.equal(merged[0].messages.length,70)
})

test('canonical teammate authorship survives a stale local copy',()=>{
 const remote=[{id:'shared',updated:1,messages:[{id:'note',role:'user',content:'Evidence',author:{id:'owner',email:'owner@example.com'}}]}]
 const local=[{id:'shared',updated:2,messages:[{id:'note',role:'user',content:'Evidence',author:{id:'wrong',email:'wrong@example.com'}}]}]
 assert.equal(mergeChats(remote,local)[0].messages[0].author.id,'owner')
})
