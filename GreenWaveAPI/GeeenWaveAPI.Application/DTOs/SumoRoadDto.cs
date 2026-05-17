using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace GreenWaveAPI.Application.DTOs
{
    public class SumoRoadDto
    {
        public int RoadId { get; set; }
        public int CongestionScore { get; set; }
        public bool Ambulance { get; set; }
    }
}
