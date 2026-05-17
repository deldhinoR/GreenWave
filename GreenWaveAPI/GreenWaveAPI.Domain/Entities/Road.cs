using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace GreenWaveAPI.Domain.Entities;

public class Road
{
    public int Id { get; set; }

    public int RoadId { get; set; }

    public int CongestionScore { get; set; }

    public bool Ambulance { get; set; }

    public int TrafficInputId { get; set; }
    public TrafficInput TrafficInput { get; set; }
}
