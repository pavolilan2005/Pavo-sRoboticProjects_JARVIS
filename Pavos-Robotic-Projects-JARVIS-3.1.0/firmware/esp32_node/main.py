import sys,json,time
from machine import Pin,PWM,ADC
CONFIG='prp_node.json';devices={};objects={}
def send(x):print(json.dumps(x));sys.stdout.flush()
def load():
 global devices
 try:
  with open(CONFIG) as f:devices=json.load(f).get('devices',{})
 except:devices={}
def setup():
 objects.clear()
 for i,d in devices.items():
  try:
   t=d.get('type','digital_output');p=int(d['pin'])
   if t=='digital_output':objects[i]=Pin(p,Pin.OUT,value=1 if d.get('active_low') else 0)
   elif t=='digital_input':objects[i]=Pin(p,Pin.IN,Pin.PULL_UP if d.get('pullup',True) else None)
   elif t=='pwm_output':objects[i]=PWM(Pin(p),freq=int(d.get('frequency',1000)),duty_u16=0)
   elif t=='analog_input':objects[i]=ADC(Pin(p))
  except Exception as e:send({'event':'device_error','device':i,'error':str(e)})
def setdev(i,state):
 d=devices[i];o=objects[i];t=d.get('type')
 if t=='digital_output':
  logical=state in ('on',True,1,'1');o.value((not logical) if d.get('active_low') else logical);return logical
 if t=='pwm_output':o.duty_u16(max(0,min(65535,int(float(state)*655.35))));return state
 raise ValueError('No es una salida')
def readdev(i):
 d=devices[i];o=objects[i]
 if d.get('type')=='analog_input':return o.read_u16()
 v=o.value();return (not v) if d.get('active_low') else bool(v)
load();setup();send({'event':'boot','protocol':'prp-node-v1','devices':len(devices)})
while True:
 try:
  line=sys.stdin.readline()
  if not line:time.sleep(.02);continue
  q=json.loads(line);cmd=q.get('cmd')
  if cmd=='ping':send({'ok':True,'message':'pong','protocol':'prp-node-v1'})
  elif cmd=='configure':devices={d['id']:d for d in q.get('devices',[])};open(CONFIG,'w').write(json.dumps({'devices':devices}));setup();send({'ok':True,'message':'Configuración aplicada'})
  elif cmd=='set':send({'ok':True,'device':q['device'],'state':setdev(q['device'],q.get('state'))})
  elif cmd=='get':send({'ok':True,'device':q['device'],'state':readdev(q['device'])})
  else:send({'ok':False,'message':'Comando desconocido'})
 except Exception as e:send({'ok':False,'message':str(e)})
