from collections import deque
import p4runtime_lib.bmv2

def add_link(links, obj1, obj2, srcport, dstport):
 if obj1 in links:
       links[obj1].append(Link(obj1=obj1, obj2=obj2, obj1_port=srcport, obj2_port=dstport))
 else:
       links[obj1] = [Link(obj1=obj1, obj2=obj2, obj1_port=srcport, obj2_port=dstport)]

class Switch(p4runtime_lib.bmv2.Bmv2SwitchConnection):
 def __repr__(self):
       return f'{self.name}'

class Host:
  def __init__(self, name, ip, mask, mac):
       self.name = name
       self.ip = ip
       self.mask = mask
       self.mac = mac

  def mask_ip(self):
       numbers = self.ip.split('.')
       if self.mask <= 8:
          numbers[0] = str(int(numbers[0]) & (2**self.mask-1))
          return f'{numbers[0]}.0.0.0'
       if self.mask <= 16:
          numbers[1] = str(int(numbers[1]) & (2**(self.mask-8)-1))
          return f'{numbers[0]}.{numbers[1]}.0.0'
       if self.mask <= 24:
          numbers[2] = str(int(numbers[2]) & (2**(self.mask-16)-1))
          return f'{numbers[0]}.{numbers[1]}.{numbers[2]}.0'
       if self.mask <= 32:
          numbers[2] = str(int(numbers[3]) & (2**(self.mask-24)-1))
          return f'{numbers[0]}.{numbers[1]}.{numbers[2]}.{numbers[3]}'

  def __str__(self):
       return f'{self.name} ip: {self.ip} mask: {self.mask} mac: {self.mac}' 
  def __repr__(self):
       return f'{self.name}' 


class Link:
  def __init__(self, obj1, obj2, obj1_port, obj2_port):
     self.obj1 = obj1
     self.obj2 = obj2
     self.obj1_port = obj1_port
     self.obj2_port = obj2_port

  def __repr__(self):
     port1 = self.obj1_port if self.obj1_port else ''
     port2 = self.obj2_port if self.obj2_port else ''
     obj1 = self.obj1.name
     obj2 = self.obj2.name
     return f'{obj1}:{port1}-{obj2}:{port2}'


class Path:
   def __init__(self, adjacency_list, src, dst):
      self.path, self.nhop, self.onehop = self.get_path(adjacency_list, src, dst)

   def get_path(self, adjacency_list, src, dst, logging=False):
      if src not in adjacency_list:
          return RuntimeError('Starting node is not in the graph')
      if logging:
         print('Get paths for', src.name, 'to', dst.name)
      queue = deque([ src ])
      visited_set = set()
      previous = {}
      out_port = {}
      onehop = False
      while len(queue) != 0:
         node = queue.popleft()
         if logging:
             print('Visited nodes:', visited_set)
             print('At', node.name)
         if node in visited_set:
             continue
         if node == dst:
             #print('Got there!')
             #print(previous)
             path = deque([dst])
             while previous[node] in previous:
                  #print('Previous hop:', previous[node])
                  path.appendleft(previous[node])
                  node = previous[node]
             path.appendleft(src)
             if len(path) == 2:
                  onehop = True
             return path, out_port[path[1]], onehop

         visited_set.add(node)
         for link in adjacency_list[node]:
             neighbor = link.obj2
             if neighbor not in out_port:
                out_port[neighbor] = link.obj1_port
             if neighbor not in visited_set:
                if logging:
                    print('To visit', neighbor.name)
                queue.append(neighbor)
                if logging and neighbor in previous:
                    print('Rewriting a previous for', neighbor)
                previous[neighbor] = node


      return None, None, None

   def print_path(self):
        if self.path == None:
            return
        i = 1
        for hop in self.path:
           print(f'Hop {i}: {hop.name}')
           i += 1
