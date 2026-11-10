"""Execute real creator route early-exit guards without importing live server.

These tests protect the one-free-export policy and stop Business footage from
using creator endpoints that bypass Business human approval/billing.
"""
import ast
import os
import pathlib
import types
import unittest

SOURCE=pathlib.Path(__file__).resolve().parent.parent/"server.py"
TREE=ast.parse(SOURCE.read_text())

def load_route(name,payload):
    fn=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==name)
    fn=ast.FunctionDef(name=fn.name,args=fn.args,body=fn.body,
                       decorator_list=[],returns=fn.returns,
                       type_comment=fn.type_comment)
    mod=ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))
    request=types.SimpleNamespace(get_json=lambda silent=True:payload)
    symbols={
      "os":os,
      "request":request,
      "jsonify":lambda obj:obj,
      "_rate_limited":lambda *a:False,
      "_paywall_on":lambda:False,
    }
    exec(compile(mod,str(SOURCE),"exec"),symbols)
    return symbols[name]

class CreatorBusinessIsolation(unittest.TestCase):
    def test_ordinary_creator_export_cannot_accept_business_source_key(self):
        source="r2://business/sources/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/"+("b"*32)+".mp4"
        for url in (source,source.upper()):
            with self.subTest(url=url):
                handler=load_route("export_clip",{"video_url":url})
                result,code=handler()
                self.assertEqual(code,409)
                self.assertEqual(result["code"],"business_export_requires_approval")
    def test_rewarm_does_not_spend_r2_or_compute_for_business_source(self):
        handler=load_route("rewarm_route",{
            "video_url":"r2://business/sources/private.mp4",
            "clips":[{"timestamp_start":0,"timestamp_end":30}]
        })
        result,code=handler()
        self.assertEqual(code,409)
        self.assertEqual(result["code"],"business_source_use_private_preview")

if __name__=="__main__":unittest.main()
