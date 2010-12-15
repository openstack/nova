Object Model
============

.. todo::  Add brief description for core models

.. graphviz::

   digraph foo {
     graph [rankdir="LR"];     node [fontsize=9 shape=box];
     Instances -> "Public IPs"      [arrowhead=crow];
     Instances -> "Security Groups" [arrowhead=crow];
     Users     -> Projects          [arrowhead=crow arrowtail=crow dir=both];
     Users     -> Keys              [arrowhead=crow];
     Instances -> Volumes           [arrowhead=crow];
     Projects  -> "Public IPs"      [arrowhead=crow];
     Projects  -> Instances         [arrowhead=crow];
     Projects  -> Volumes           [arrowhead=crow];
     Projects  -> Images            [arrowhead=crow];
     Images    -> Instances         [arrowhead=crow];
     Projects  -> "Security Groups" [arrowhead=crow];
     "Security Groups" -> Rules     [arrowhead=crow];
   }


Users
-----

Projects
--------


Images
------


Instances
---------


Volumes
-------


Security Groups
---------------


VLANs
-----


IP Addresses
------------
