import assert from 'node:assert/strict';
import {postingTimeChoices} from '../src/lib/businessPostingTime.mjs';
import {test} from 'node:test';

test('normal business time resolves to an exact UTC instant without offset arithmetic',()=>{
  assert.deepEqual(postingTimeChoices('2027-07-15T09:00','Europe/London').choices,
    [{utcOffsetMinutes:60,utcTime:'2027-07-15T08:00:00.000Z'}]);
  assert.deepEqual(postingTimeChoices('2027-01-15T09:00','Asia/Kathmandu').choices,
    [{utcOffsetMinutes:345,utcTime:'2027-01-15T03:15:00.000Z'}]);
});
test('repeated hours expose both distinct instants and spring gaps expose none',()=>{
  assert.deepEqual(postingTimeChoices('2027-10-31T01:30','Europe/London').choices,
    [{utcOffsetMinutes:60,utcTime:'2027-10-31T00:30:00.000Z'},
     {utcOffsetMinutes:0,utcTime:'2027-10-31T01:30:00.000Z'}]);
  assert.equal(postingTimeChoices('2027-03-28T01:30','Europe/London').error,'nonexistent');
});
test('half hour daylight saving and invalid user inputs are handled explicitly',()=>{
  assert.equal(postingTimeChoices('2027-04-04T01:45','Australia/Lord_Howe').choices.length,2);
  for(const value of ['2027-02-30T09:00','bad','2027-01-01T25:00'])
    assert.equal(postingTimeChoices(value,'UTC').error,'invalid_time');
  assert.equal(postingTimeChoices('2027-01-01T09:00','Made/Up').error,'invalid_zone');
  assert.deepEqual(postingTimeChoices('','UTC').choices,[]);
});
