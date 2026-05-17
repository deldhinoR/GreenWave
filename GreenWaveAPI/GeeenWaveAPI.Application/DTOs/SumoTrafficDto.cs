using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace GreenWaveAPI.Application.DTOs
{
    public class SumoTrafficDto
    {
        public DateTime ReceivedTime { get; set; }
        public DateTime? SavedTime { get; set; }

        public int JunctionId { get; set; }

        public List<SumoRoadDto> Roads { get; set; }
    }

}
