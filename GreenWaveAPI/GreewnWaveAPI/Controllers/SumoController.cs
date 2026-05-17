using MediatR;
using Microsoft.AspNetCore.Mvc;
using GreenWaveAPI.Application.DTOs;
using GreenWaveAPI.Application.Features.Traffic.Queries;
using System.Threading.Tasks;

namespace GreenWaveAPI.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class SumoController : ControllerBase
    {
        private readonly IMediator _mediator;

        public SumoController(IMediator mediator)
        {
            _mediator = mediator;
        }

        [HttpGet("traffic/{junctionId}")]
        public async Task<IActionResult> GetLatestTraffic(int junctionId)
        {
            var data = await _mediator.Send(new GetLatestTrafficQuery { JunctionId = junctionId });

            if (data == null)
                return NotFound("No traffic data found.");

            return Ok(data);
        }
    }
}